//
//  ContentView.swift
//  Ortsbild
//
//  Created by Joshua Kehrer on 26.10.26.
//

import SwiftUI

/// The list of reports. The account sheet sits here once, for the list and for every chat that is pushed on top of it.
struct ContentView: View {
    @Environment(AuthViewModel.self) private var auth

    var body: some View {
        TicketListView()
            .sheet(isPresented: Binding(get: { auth.isSheetPresented }, set: { auth.isSheetPresented = $0 })) {
                AccountSheet()
            }
    }
}

#Preview {
    ContentView()
        .environment(TicketStore.preview)
        .environment(AuthViewModel(service: MockAuthService()))
}
