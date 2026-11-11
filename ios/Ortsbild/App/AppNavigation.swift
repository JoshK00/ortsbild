//
//  AppNavigation.swift
//  Ortsbild
//

import Foundation

/// The two tabs of the app.
enum AppTab: Hashable {
    /// The chats: a photo becomes a report.
    case report
    /// The dashboard with the map and the list of released reports.
    case dashboard
}

/// Which tab is open, and which case the dashboard should show. One object for the whole app, so the chat can open the map.
@MainActor
@Observable
final class AppNavigation {
    var selectedTab: AppTab = .report
    /// The case the dashboard shows when it opens (deep link `#case=<id>`), `nil` for the plain dashboard.
    private(set) var dashboardCaseID: String?

    /// Switches to the map. `caseID` is the case to highlight, `nil` if the server sent none.
    func showDashboard(caseID: String? = nil) {
        dashboardCaseID = caseID
        selectedTab = .dashboard
    }
}
