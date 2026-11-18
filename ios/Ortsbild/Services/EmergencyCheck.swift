//
//  EmergencyCheck.swift
//  Ortsbild
//

import Foundation

/// Emergency hint before anything is sent: only a pointer to 110 / 112, no report.
enum EmergencyCheck {
    private static let keywords = ["feuer", "brand", "verletzt", "gewalt", "unfall"]

    static func matches(_ text: String?) -> Bool {
        let lowered = text?.lowercased() ?? ""
        return keywords.contains(where: lowered.contains)
    }
}
