// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NativeContract",
    products: [
        .library(name: "NativeContract", targets: ["NativeContract"]),
        .executable(name: "TraceRunner", targets: ["TraceRunner"]),
    ],
    targets: [
        .target(name: "NativeContract"),
        .executableTarget(name: "TraceRunner", dependencies: ["NativeContract"]),
        .testTarget(name: "NativeContractTests", dependencies: ["NativeContract"]),
    ]
)
