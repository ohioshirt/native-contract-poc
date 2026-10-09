import AsyncNativeContract
import Foundation

let input = FileHandle.standardInput.readDataToEndOfFile()
do {
    let output = try AsyncTraceDocumentProcessor.process(input)
    FileHandle.standardOutput.write(output)
    FileHandle.standardOutput.write(Data([0x0a]))
} catch {
    FileHandle.standardError.write(Data("AsyncTraceRunner: \(error)\n".utf8))
    exit(EXIT_FAILURE)
}
