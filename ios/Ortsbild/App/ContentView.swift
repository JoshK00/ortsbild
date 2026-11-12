//
//  ContentView.swift
//  Ortsbild
//
//  Created by Joshua Kehrer on 26.10.26.
//

import SwiftUI

/// The two tabs: the reports (a chat per report) and the dashboard with the map. The account sheet sits here once, for the list,
/// for every chat that is pushed on top of it and for the dashboard.
struct ContentView: View {
    @Environment(AuthViewModel.self) private var auth
    @Environment(AppNavigation.self) private var navigation

    var body: some View {
        @Bindable var navigation = navigation
        TabView(selection: $navigation.selectedTab) {
            Tab("Melden", systemImage: "camera", value: AppTab.report) {
                TicketListView()
            }
            Tab("Karte", systemImage: "map", value: AppTab.dashboard) {
                DashboardView()
            }
        }
            .sheet(isPresented: Binding(get: { auth.isSheetPresented }, set: { auth.isSheetPresented = $0 })) {
                AccountSheet()
            }
    }
}

#Preview {
    ContentView()
        .environment(TicketStore.preview)
        .environment(AuthViewModel(service: MockAuthService()))
        .environment(AppNavigation())
}
