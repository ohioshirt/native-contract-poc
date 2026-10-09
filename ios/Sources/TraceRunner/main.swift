import Foundation
import NativeContract
import Darwin

let input = FileHandle.standardInput.readDataToEndOfFile()
do {
    let output = try TraceDocumentProcessor.process(input)
    FileHandle.standardOutput.write(output)
    FileHandle.standardOutput.write(Data([0x0A]))
} catch {
    let message = "TraceRunner: \(error)\n"
    FileHandle.standardError.write(Data(message.utf8))
    exit(EXIT_FAILURE)
}
