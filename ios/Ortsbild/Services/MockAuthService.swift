//
//  MockAuthService.swift
//  Ortsbild
//

import Foundation

struct MockAuthService: AuthService {
    // TODO: Replace with real backend call (`POST /auth/apple`): the backend verifies the identity token and maps the Apple user ID to a `reporter_id`
    func signIn(identityToken: Data, authorizationCode: Data) async throws -> Reporter {
        try await Task.sleep(for: .milliseconds(600))
        return Reporter(id: UUID().uuidString)
    }

    // TODO: Discard the session token from the Keychain (Keychain storage is not implemented yet)
    func signOut() async {}

    // TODO: Call the backend deletion endpoint and revoke the Sign in with Apple token (required by the App Store)
    func deleteAccount() async throws {
        try await Task.sleep(for: .milliseconds(600))
    }
}
