import Foundation

final class URLSessionRefreshTransport: NSObject, RefreshTransport, URLSessionDataDelegate, URLSessionTaskDelegate, @unchecked Sendable {
    typealias CompletionObserver = @Sendable (Completion) -> Void

    private final class RequestContext: @unchecked Sendable {
        let slot: RefreshSlot
        let completion: @Sendable (Completion) -> Void
        let observer: CompletionObserver?
        var body = Data()
        var statusCode: Int?
        var responseTooLarge = false
        var handle: URLSessionTransportHandle?

        init(slot: RefreshSlot, observer: CompletionObserver?, completion: @escaping @Sendable (Completion) -> Void) {
            self.slot = slot
            self.observer = observer
            self.completion = completion
        }
    }

    private let baseURL: URL
    private let runId: String
    private let lock = NSLock()
    private var contexts: [Int: RequestContext] = [:]
    private var session: URLSession!

    init(
        baseURL: URL,
        runId: String,
        onCompletionCaptured: CompletionObserver? = nil,
        urlProtocolClasses: [AnyClass]? = nil
    ) {
        self.baseURL = baseURL
        self.runId = runId
        self.onCompletionCaptured = onCompletionCaptured
        super.init()

        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 75
        configuration.timeoutIntervalForResource = 75
        configuration.waitsForConnectivity = false
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        if let urlProtocolClasses { configuration.protocolClasses = urlProtocolClasses }
        let delegateQueue = OperationQueue()
        delegateQueue.name = "native-contract.refresh-delegate"
        delegateQueue.maxConcurrentOperationCount = 1
        self.session = URLSession(configuration: configuration, delegate: self, delegateQueue: delegateQueue)
    }

    private let onCompletionCaptured: CompletionObserver?

    func start(
        slot: RefreshSlot,
        credential: Credential,
        completion: @escaping @Sendable (Completion) -> Void
    ) -> any TransportHandle {
        let request: URLRequest
        do {
            request = try RefreshWire.makeRequest(baseURL: baseURL, runId: runId, slot: slot, credential: credential)
        } catch {
            let captured = Completion(slot: slot, outcome: .failure("invalidRequest"))
            DispatchQueue.global(qos: .userInitiated).async { [onCompletionCaptured] in
                onCompletionCaptured?(captured)
                completion(captured)
            }
            return CompletedTransportHandle()
        }

        let context = RequestContext(slot: slot, observer: onCompletionCaptured, completion: completion)
        let task = session.dataTask(with: request)
        let handle = URLSessionTransportHandle(task: task)
        context.handle = handle
        lock.withLock { contexts[task.taskIdentifier] = context }
        task.resume()
        return handle
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        guard let response = response as? HTTPURLResponse else {
            lock.withLock { contexts[dataTask.taskIdentifier]?.statusCode = -1 }
            completionHandler(.cancel)
            return
        }
        lock.withLock { contexts[dataTask.taskIdentifier]?.statusCode = response.statusCode }
        completionHandler(.allow)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive data: Data
    ) {
        let shouldCancel = lock.withLock { () -> Bool in
            guard let context = contexts[dataTask.taskIdentifier] else { return true }
            guard context.body.count + data.count <= RefreshWire.maximumBodyBytes else {
                context.responseTooLarge = true
                return true
            }
            context.body.append(data)
            return false
        }
        if shouldCancel { dataTask.cancel() }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let context = lock.withLock({ contexts.removeValue(forKey: task.taskIdentifier) }) else { return }
        let outcome: RefreshOutcome
        if context.responseTooLarge {
            outcome = .failure("malformed")
        } else if error != nil {
            outcome = .failure("disconnected")
        } else if let statusCode = context.statusCode {
            outcome = RefreshWire.parseResponse(
                context.body,
                statusCode: statusCode,
                expectedRunId: runId,
                slot: context.slot
            )
        } else {
            outcome = .failure("disconnected")
        }
        let result = Completion(slot: context.slot, outcome: outcome)
        context.observer?(result)
        context.completion(result)
        context.handle?.markCompleted()
    }
}

private struct CompletedTransportHandle: TransportHandle {
    func cancel() {}
}

private final class TransportCompletionLatch: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false

    var isCompleted: Bool { lock.withLock { completed } }
    func markCompleted() { lock.withLock { completed = true } }
}

private final class URLSessionTransportHandle: FencedTransportHandle, @unchecked Sendable {
    private let task: URLSessionTask
    private let completionSignal = TransportCompletionLatch()

    init(task: URLSessionTask) { self.task = task }

    func cancel() { task.cancel() }

    func markCompleted() { completionSignal.markCompleted() }

    func cancelAndWait(timeoutMillis: Int64) async throws {
        guard timeoutMillis > 0 else { throw TransportFenceError.timeout }
        task.cancel()
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .milliseconds(timeoutMillis))
        while !completionSignal.isCompleted {
            guard clock.now < deadline else { throw TransportFenceError.timeout }
            try await Task.sleep(for: .milliseconds(5))
        }
    }
}

private enum TransportFenceError: Error {
    case timeout
}
