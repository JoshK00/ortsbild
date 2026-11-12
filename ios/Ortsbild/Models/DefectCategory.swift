//
//  DefectCategory.swift
//  Ortsbild
//

import Foundation

/// The kinds of defects the backend knows, with the code it uses and the German name for the chat.
/// "Sonstiges" (`other`) is not here: it is not a defect, it is what the backend answers when none of these fits.
nonisolated enum DefectCategory: String, CaseIterable, Sendable {
    case litter
    case graffiti
    case streetLight = "street_light"
    case playgroundEquipment = "playground_equipment"
    case pothole
    case tree

    var title: String {
        switch self {
        case .litter: "Müll"
        case .graffiti: "Graffiti"
        case .streetLight: "Straßenbeleuchtung"
        case .playgroundEquipment: "Spielgerät"
        case .pothole: "Schlagloch"
        case .tree: "Baum"
        }
    }

    /// The category whose German name is `title`, for the button the user tapped.
    init?(title: String) {
        guard let match = Self.allCases.first(where: { $0.title == title }) else { return nil }
        self = match
    }
}
