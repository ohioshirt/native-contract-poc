import SwiftUI

@main
struct NativeContractDemoApp: App {
    @StateObject private var environment = DemoEnvironment()

    var body: some Scene {
        WindowGroup {
            DemoView(model: environment.viewModel)
        }
    }
}
