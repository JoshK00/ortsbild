//
//  OrtsbildApp.swift
//  Ortsbild
//
//  Created by Joshua Kehrer on 26.10.26.
//

import SwiftUI

@main
struct OrtsbildApp: App {
    @State private var auth = AuthViewModel()
    @State private var store = TicketStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(auth)
                .environment(store)
                .task {
                    // Deleting the account also removes the history on this phone
                    auth.onAccountDeleted = { store.deleteAll() }
                }
        }
    }
}
