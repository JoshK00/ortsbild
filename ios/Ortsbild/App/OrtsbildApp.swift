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
    @State private var navigation = AppNavigation()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .preferredColorScheme(.dark)
                .tint(.white)
                .environment(auth)
                .environment(store)
                .environment(navigation)
                .task {
                    // Deleting the account also removes the history on this phone
                    auth.onAccountDeleted = { store.deleteAll() }
                }
        }
    }
}
