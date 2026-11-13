//
//  AppServices.swift
//  Ortsbild
//

import Foundation

/// The real services of the app, created once. Previews pass the mock of the sign-in (`MockAuthService`) instead.
enum AppServices {
    static let client = BackendClient(baseURL: AppConfig.backendURL)
    static let auth: AuthService = BackendAuthService(client: client)
    static let reports: ReportService = BackendReportService(client: client)
}
