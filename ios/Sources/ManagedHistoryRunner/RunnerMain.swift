import Foundation

@available(macOS 10.15, iOS 13, tvOS 13, watchOS 6, *)
@main
struct ManagedHistoryRunnerMain {
    static func main() async {
        let input = FileHandle.standardInput.readDataToEndOfFile()
        do {
            let output = try await ManagedHistoryProcessor.process(input)
            FileHandle.standardOutput.write(output)
            FileHandle.standardOutput.write(Data([0x0a]))
        } catch {
            FileHandle.standardError.write(Data("ManagedHistoryRunner: \(error)\n".utf8))
            exit(EXIT_FAILURE)
        }
    }
}
