//
//  Reporter.swift
//  Ortsbild
//

import Foundation

/// The signed-in user as the app sees them. Only the pseudonymous ID is known here,
/// the mapping to the Apple ID exists exclusively in the backend.
struct Reporter: Equatable {
    /// Random ID issued by the backend (`reporter_id`), never the Apple user identifier.
    let id: String
}

enum AuthState: Equatable {
    case signedOut
    case signedIn(Reporter)
}
