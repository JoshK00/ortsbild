//
//  AuthService.swift
//  Ortsbild
//

import Foundation

/// Interface to the backend's authentication. `MockAuthService` is for previews.
protocol AuthService {
    /// The reporter of the session that is still in the Keychain, if there is one.
    func restoreSession() async -> Reporter?
    /// Exchanges the Sign in with Apple identity token for a pseudonymous reporter.
    /// `nonce` is the raw value whose SHA-256 went into the request to Apple.
    func signIn(identityToken: Data, nonce: String) async throws -> Reporter
    func signOut() async
    /// Deletes the account and the associated data.
    func deleteAccount() async throws
}
