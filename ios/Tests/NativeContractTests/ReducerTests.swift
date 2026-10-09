import XCTest
@testable import NativeContract

final class ReducerTests: XCTestCase {
    func testInitialStateIsUnauthenticated() {
        XCTAssertEqual(AuthReducer().state, .unauthenticated)
    }

    func testAllStateEventPairsHaveExpectedResults() {
        let cases: [(AuthState, AuthEvent, AuthState, [AuthEffect])] = [
            (.unauthenticated, .loginSucceeded, .authenticated, []),
            (.unauthenticated, .logout, .unauthenticated, []),
            (.unauthenticated, .tokenExpired, .unauthenticated, []),
            (.unauthenticated, .refreshSucceeded, .unauthenticated, []),
            (.unauthenticated, .refreshFailed, .unauthenticated, []),
            (.authenticated, .loginSucceeded, .authenticated, [.clearCredentials]),
            (.authenticated, .logout, .unauthenticated, [.clearCredentials]),
            (.authenticated, .tokenExpired, .refreshing, [.requestTokenRefresh]),
            (.authenticated, .refreshSucceeded, .authenticated, []),
            (.authenticated, .refreshFailed, .authenticated, []),
            (.refreshing, .loginSucceeded, .refreshing, []),
            (.refreshing, .logout, .refreshing, []),
            (.refreshing, .tokenExpired, .refreshing, []),
            (.refreshing, .refreshSucceeded, .authenticated, []),
            (.refreshing, .refreshFailed, .unauthenticated, [.clearCredentials]),
        ]

        for (initial, event, expectedState, expectedEffects) in cases {
            var reducer = AuthReducer(initialState: initial)
            let result = reducer.handle(event)
            XCTAssertEqual(result.state, expectedState, "\(initial) × \(event)")
            XCTAssertEqual(result.effects, expectedEffects, "\(initial) × \(event)")
            XCTAssertEqual(reducer.state, expectedState, "\(initial) × \(event)")
        }
    }

    func testRepeatedLoginWhileAuthenticatedClearsCredentialsEachTime() {
        var reducer = AuthReducer(initialState: .authenticated)

        let first = reducer.handle(.loginSucceeded)
        XCTAssertEqual(first.state, .authenticated)
        XCTAssertEqual(first.effects, [.clearCredentials])

        let second = reducer.handle(.loginSucceeded)
        XCTAssertEqual(second.state, .authenticated)
        XCTAssertEqual(second.effects, [.clearCredentials])
        XCTAssertEqual(reducer.state, .authenticated)
    }
}
