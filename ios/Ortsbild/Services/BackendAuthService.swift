//
//  BackendAuthService.swift
//  Ortsbild
//

import Foundation

extension Notification.Name {
    /// The backend refused to renew the session for good, the user has to sign in again.
    static let backendSessionEnded = Notification.Name("backendSessionEnded")
}

/// Sign in with Apple against the backend: the identity token is swapped for our own session.
struct BackendAuthService: AuthService {
    let client: BackendClient

    func restoreSession() async -> Reporter? {
        await client.currentSession().map { Reporter(id: $0.reporterID) }
    }

    func signIn(identityToken: Data, nonce: String) async throws -> Reporter {
        guard let token = String(data: identityToken, encoding: .utf8) else { throw BackendError.invalidResponse }
        let session = try await client.signIn(identityToken: token, nonce: nonce)
        return Reporter(id: session.reporterID)
    }

    func signOut() async {
        await client.signOut()
    }

    // TODO: Also revoke the Sign in with Apple token at Apple (App Store rule 5.1.1(v)). That needs the authorization
    // code from the sign-in and a key (.p8) of the developer account on the server.
    func deleteAccount() async throws {
        try await client.deleteAccount()
    }
}
