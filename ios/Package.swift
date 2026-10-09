// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NativeContract",
    products: [
        .library(name: "NativeContract", targets: ["NativeContract"]),
        .library(name: "AsyncNativeContract", targets: ["AsyncNativeContract"]),
        .executable(name: "TraceRunner", targets: ["TraceRunner"]),
        .executable(name: "AsyncTraceRunner", targets: ["AsyncTraceRunner"]),
    ],
    targets: [
        .target(name: "NativeContract"),
        .target(name: "AsyncNativeContract", dependencies: ["NativeContract"]),
        .executableTarget(name: "TraceRunner", dependencies: ["NativeContract"]),
        .executableTarget(name: "AsyncTraceRunner", dependencies: ["AsyncNativeContract"]),
        .testTarget(name: "NativeContractTests", dependencies: ["NativeContract"]),
        .testTarget(name: "AsyncNativeContractTests", dependencies: ["AsyncNativeContract"]),
    ]
)
