//
//  AppConfig.swift
//  Ortsbild
//

import Foundation

/// Settings of the app. Nothing secret belongs here: the app ships to every user's phone.
enum AppConfig {
    // TODO: Replace the free sslip.io name with the real domain of the team once there is one.
    static let backendURL = URL(string: "https://217-154-175-68.sslip.io")!
}
