import Foundation
import Network
import XCTest
import AsyncNativeContract
@testable import NativeContractDemo

final class TransportTests: XCTestCase {
    func testRefreshRequestUsesCapturedSlotAndCanonicalWireIdentity() async throws {
        let slot = try await makeSlot(account: .a, requestIdStart: 41)
        let credential = Credential.demo(account: .a, version: 0)
        let request = try RefreshWire.makeRequest(
            baseURL: URL(string: "http://127.0.0.1:8080")!,
            runId: "task4-run",
            slot: slot,
            credential: credential
        )
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: try XCTUnwrap(request.httpBody)) as? [String: Any])

        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/v1/refresh")
        XCTAssertEqual(object.keys.sorted(), ["account", "refreshToken", "requestId", "requestTag", "runId", "version"])
        XCTAssertEqual(object["runId"] as? String, "task4-run")
        XCTAssertEqual(object["requestTag"] as? String, "task4-p1:refresh:3")
        XCTAssertEqual(object["requestId"] as? String, "41")
        XCTAssertEqual(object["account"] as? String, "A")
        XCTAssertEqual(object["refreshToken"] as? String, "demo-A-v0")
        XCTAssertEqual(object["version"] as? Int, 1)
    }

    func testWrongCorrelationCannotBecomeRefreshSuccess() async throws {
        let slot = try await makeSlot(account: .a, requestIdStart: 1)
        let body = Data(#"{"version":1,"runId":"task4-run","requestTag":"task4-p1:refresh:3:wrong-correlation","outcome":"success","credential":{"account":"A","version":1,"accessToken":"demo-A-v1","refreshToken":"demo-A-v1"}}"#.utf8)

        let outcome = RefreshWire.parseResponse(
            body,
            statusCode: 200,
            expectedRunId: "task4-run",
            slot: slot
        )

        XCTAssertEqual(outcome, .failure("wrongCorrelation"))
    }

    func testMalformedAndDuplicateKeyResponsesBecomeFailure() async throws {
        let slot = try await makeSlot(account: .a, requestIdStart: 1)
        let malformed = Data(#"{"version":1,"runId":"task4-run","requestTag":"task4-p1:refresh:3","outcome": "#.utf8)
        let duplicate = Data(#"{"version":1,"version":1,"runId":"task4-run","requestTag":"task4-p1:refresh:3","outcome":"success","credential":{"account":"A","version":1,"accessToken":"demo-A-v1","refreshToken":"demo-A-v1"}}"#.utf8)

        XCTAssertEqual(RefreshWire.parseResponse(malformed, statusCode: 200, expectedRunId: "task4-run", slot: slot), .failure("malformed"))
        XCTAssertEqual(RefreshWire.parseResponse(duplicate, statusCode: 200, expectedRunId: "task4-run", slot: slot), .failure("malformed"))
    }

    /// The wire carries integers only; Foundation would round `1.0000000000000001` to 1
    /// before any NSNumber check, so non-integer number literals are rejected while scanning.
    func testNonIntegerNumberLiteralsAreMalformedBeforeFoundationRoundsThem() async throws {
        let slot = try await makeSlot(account: .a, requestIdStart: 1)
        func body(envelope: String, credential: String) -> Data {
            Data(#"{"version":\#(envelope),"runId":"task4-run","requestTag":"task4-p1:refresh:3","outcome":"success","credential":{"account":"A","version":\#(credential),"accessToken":"demo-A-v1","refreshToken":"demo-A-v1"}}"#.utf8)
        }
        XCTAssertEqual(
            RefreshWire.parseResponse(body(envelope: "1", credential: "1"), statusCode: 200, expectedRunId: "task4-run", slot: slot),
            .success(.demo(account: .a, version: 1))
        )
        for literal in ["1.0", "1e0", "1E0", "1.0000000000000001", "10e-1"] {
            for (envelope, credential) in [(literal, "1"), ("1", literal)] {
                XCTAssertEqual(
                    RefreshWire.parseResponse(body(envelope: envelope, credential: credential), statusCode: 200, expectedRunId: "task4-run", slot: slot),
                    .failure("malformed"),
                    "envelope \(envelope), credential \(credential)"
                )
            }
        }
    }

    func testServerFailureCodesRemainRedactedAndStable() async throws {
        let slot = try await makeSlot(account: .a, requestIdStart: 1)
        let body = Data(#"{"version":1,"runId":"task4-run","requestTag":"task4-p1:refresh:3","outcome":"failure","failure":"server"}"#.utf8)

        XCTAssertEqual(RefreshWire.parseResponse(body, statusCode: 500, expectedRunId: "task4-run", slot: slot), .failure("server"))
    }

    func testURLSessionTransportSendsAndCompletesOneCapturedSlot() async throws {
        let slot = try await makeSlot(account: .a, requestIdStart: 41)
        let body = Data(#"{"version":1,"runId":"task4-run","requestTag":"task4-p1:refresh:3","outcome":"success","credential":{"account":"A","version":1,"accessToken":"demo-A-v1","refreshToken":"demo-A-v1"}}"#.utf8)
        URLProtocolStubState.shared.configure(statusCode: 200, body: body)
        let transport = URLSessionRefreshTransport(
            baseURL: URL(string: "http://127.0.0.1:8080")!,
            runId: "task4-run",
            urlProtocolClasses: [URLProtocolStub.self]
        )
        let completed = expectation(description: "URLSession completion")
        let result = CompletionBox()
        _ = transport.start(slot: slot, credential: .demo(account: .a, version: 0)) { completion in
            result.store(completion)
            completed.fulfill()
        }
        await fulfillment(of: [completed], timeout: 3)

        let completion = try XCTUnwrap(result.value)
        let request = try XCTUnwrap(URLProtocolStubState.shared.request)
        let requestBody = try streamedBody(of: request)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: requestBody) as? [String: Any])
        XCTAssertEqual(request.url?.path, "/v1/refresh")
        XCTAssertEqual(object["requestTag"] as? String, slot.wireTag)
        XCTAssertEqual(object["requestId"] as? String, "41")
        XCTAssertTrue(completion.slot === slot)
        XCTAssertEqual(completion.outcome, .success(.demo(account: .a, version: 1)))
    }

    func testURLSessionTransportCompletesAgainstRealLoopbackHTTP() async throws {
        let server = try LoopbackRefreshHTTPServer()
        let port = try await server.start()
        defer { server.stop() }

        let slot = try await makeSlot(account: .a, requestIdStart: 41)
        let transport = URLSessionRefreshTransport(
            baseURL: URL(string: "http://127.0.0.1:\(port)")!,
            runId: "task4-loopback"
        )
        let completed = expectation(description: "real loopback URLSession completion")
        let result = CompletionBox()
        _ = transport.start(slot: slot, credential: .demo(account: .a, version: 0)) { completion in
            result.store(completion)
            completed.fulfill()
        }
        await fulfillment(of: [completed], timeout: 5)

        let completion = try XCTUnwrap(result.value)
        XCTAssertTrue(completion.slot === slot)
        XCTAssertEqual(completion.outcome, .success(.demo(account: .a, version: 1)))
        let requestBody = try XCTUnwrap(server.requestBody)
        let request = try XCTUnwrap(JSONSerialization.jsonObject(with: requestBody) as? [String: Any])
        XCTAssertEqual(request["runId"] as? String, "task4-loopback")
        XCTAssertEqual(request["requestTag"] as? String, slot.wireTag)
        XCTAssertEqual(request["requestId"] as? String, "41")
    }

    private func makeSlot(account: CredentialAccount, requestIdStart: Int64) async throws -> RefreshSlot {
        let managed = ManagedAsyncSession(nextRequestId: requestIdStart)
        _ = await managed.handle(.loginSucceeded)
        let result = await managed.handle(.tokenExpired)
        guard let request = result.effects.compactMap({ effect -> RefreshRequest? in
            if case let .requestTokenRefresh(value) = effect { return value }
            return nil
        }).first else {
            throw TransportTestError.noRequest
        }
        let processId = "task4-p1"
        let process = ProcessContext(processInstanceId: processId, launchOrdinal: 1, attemptId: "task4", scenarioId: "APP-13")
        return RefreshSlot(
            slotId: "slot-\(account.rawValue)1",
            request: request,
            epoch: SessionEpoch(id: "epoch-task4"),
            issuanceCommandId: 3,
            wireTag: "\(process.processInstanceId):refresh:3",
            account: account,
            seedVersion: 0,
            ownerId: "owner-task4"
        )
    }

    private func streamedBody(of request: URLRequest) throws -> Data {
        if let body = request.httpBody { return body }
        let stream = try XCTUnwrap(request.httpBodyStream)
        stream.open()
        defer { stream.close() }
        var bytes = [UInt8](repeating: 0, count: 2048)
        var result = Data()
        while true {
            let count = stream.read(&bytes, maxLength: bytes.count)
            if count < 0 { throw stream.streamError ?? TransportTestError.noRequest }
            if count == 0 { return result }
            result.append(contentsOf: bytes.prefix(count))
        }
    }
}

private enum TransportTestError: Error {
    case noRequest
}

private final class CompletionBox: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Completion?

    var value: Completion? { lock.withLock { stored } }
    func store(_ completion: Completion) { lock.withLock { stored = completion } }
}

private final class LoopbackRefreshHTTPServer: @unchecked Sendable {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "native-contract.test.loopback-http")
    private let lock = NSLock()
    private var capturedRequestBody: Data?

    var requestBody: Data? { lock.withLock { capturedRequestBody } }

    init() throws {
        listener = try NWListener(using: .tcp, on: .any)
    }

    func start() async throws -> UInt16 {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<UInt16, Error>) in
            listener.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    guard let port = self?.listener.port?.rawValue else {
                        continuation.resume(throwing: LoopbackHTTPError.noPort)
                        return
                    }
                    continuation.resume(returning: port)
                case let .failed(error):
                    continuation.resume(throwing: error)
                default:
                    break
                }
            }
            listener.newConnectionHandler = { [weak self] connection in
                connection.start(queue: self?.queue ?? .global())
                self?.receive(connection, bytes: Data())
            }
            listener.start(queue: queue)
        }
    }

    func stop() { listener.cancel() }

    private func receive(_ connection: NWConnection, bytes: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 4_096) { [weak self] chunk, _, complete, error in
            guard let self else { connection.cancel(); return }
            if let error { connection.cancel(); _ = error; return }
            var received = bytes
            if let chunk { received.append(chunk) }
            if let body = Self.completeRequestBody(received) {
                self.lock.withLock { self.capturedRequestBody = body }
                self.respond(to: connection, requestBody: body)
            } else if complete {
                connection.cancel()
            } else {
                self.receive(connection, bytes: received)
            }
        }
    }

    private func respond(to connection: NWConnection, requestBody: Data) {
        guard let request = try? JSONSerialization.jsonObject(with: requestBody) as? [String: Any],
              let runId = request["runId"] as? String,
              let requestTag = request["requestTag"] as? String,
              let account = request["account"] as? String else {
            connection.cancel()
            return
        }
        let token = "demo-\(account)-v1"
        let response: [String: Any] = [
            "version": 1,
            "runId": runId,
            "requestTag": requestTag,
            "outcome": "success",
            "credential": [
                "account": account,
                "version": 1,
                "accessToken": token,
                "refreshToken": token,
            ],
        ]
        guard let body = try? JSONSerialization.data(withJSONObject: response, options: [.sortedKeys]) else {
            connection.cancel()
            return
        }
        var wire = Data("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n".utf8)
        wire.append(body)
        connection.send(content: wire, completion: .contentProcessed { _ in connection.cancel() })
    }

    private static func completeRequestBody(_ bytes: Data) -> Data? {
        guard let separator = bytes.range(of: Data("\r\n\r\n".utf8)) else { return nil }
        let headers = String(decoding: bytes[..<separator.lowerBound], as: UTF8.self)
            .components(separatedBy: "\r\n")
        guard let lengthHeader = headers.first(where: { $0.lowercased().hasPrefix("content-length:") }),
              let length = Int(lengthHeader.dropFirst("content-length:".count).trimmingCharacters(in: .whitespaces)),
              length >= 0 else { return nil }
        let bodyStart = separator.upperBound
        guard bytes.distance(from: bodyStart, to: bytes.endIndex) >= length,
              let bodyEnd = bytes.index(bodyStart, offsetBy: length, limitedBy: bytes.endIndex) else { return nil }
        return Data(bytes[bodyStart..<bodyEnd])
    }
}

private enum LoopbackHTTPError: Error {
    case noPort
}

private final class URLProtocolStubState: @unchecked Sendable {
    struct Response {
        let statusCode: Int
        let body: Data
    }

    static let shared = URLProtocolStubState()
    private let lock = NSLock()
    private var configured: Response?
    private var observed: URLRequest?

    var response: Response? { lock.withLock { configured } }
    var request: URLRequest? { lock.withLock { observed } }

    func configure(statusCode: Int, body: Data) {
        lock.withLock {
            configured = Response(statusCode: statusCode, body: body)
            observed = nil
        }
    }

    func record(_ request: URLRequest) { lock.withLock { observed = request } }
}

private final class URLProtocolStub: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        URLProtocolStubState.shared.record(request)
        guard let configured = URLProtocolStubState.shared.response,
              let url = request.url,
              let response = HTTPURLResponse(
                  url: url,
                  statusCode: configured.statusCode,
                  httpVersion: "HTTP/1.1",
                  headerFields: ["Content-Type": "application/json"]
              ) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: configured.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
