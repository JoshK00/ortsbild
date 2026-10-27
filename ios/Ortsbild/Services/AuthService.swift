//
//  AuthService.swift
//  Ortsbild
//

import Foundation

/// Interface to the backend's authentication. The app runs against `MockAuthService` first.
protocol AuthService {
    /// Exchanges the Sign in with Apple tokens for a pseudonymous reporter.
    func signIn(identityToken: Data, authorizationCode: Data) async throws -> Reporter
    func signOut() async
    /// Deletes the account and the associated data.
    func deleteAccount() async throws
}
