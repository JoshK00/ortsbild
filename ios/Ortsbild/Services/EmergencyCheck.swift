//
//  EmergencyCheck.swift
//  Ortsbild
//

import Foundation

/// Emergency hint before anything is sent: only a pointer to 110 / 112, no report.
enum EmergencyCheck {
    // TODO: Emergency detection will later run through the classification (photo and text), for now only a keyword search in the text
    private static let keywords = ["feuer", "brand", "verletzt", "gewalt", "unfall"]

    static func matches(_ text: String?) -> Bool {
        let lowered = text?.lowercased() ?? ""
        return keywords.contains(where: lowered.contains)
    }
}
