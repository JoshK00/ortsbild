//
//  MockAuthService.swift
//  Ortsbild
//

import Foundation

/// Stand-in for previews, it does not talk to the backend.
struct MockAuthService: AuthService {
    func restoreSession() async -> Reporter? { nil }

    func signIn(identityToken: Data, nonce: String) async throws -> Reporter {
        try await Task.sleep(for: .milliseconds(600))
        return Reporter(id: UUID().uuidString)
    }

    func signOut() async {}

    func deleteAccount() async throws {
        try await Task.sleep(for: .milliseconds(600))
    }
}
