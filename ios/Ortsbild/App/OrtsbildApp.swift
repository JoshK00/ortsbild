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

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(auth)
        }
    }
}
