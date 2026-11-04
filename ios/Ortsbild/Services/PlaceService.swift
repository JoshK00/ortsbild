//
//  PlaceService.swift
//  Ortsbild
//

import CoreLocation
import MapKit

/// The address of a position as the phone's geocoder found it. All parts are optional.
/// It is sent along with the report and helps the backend to find the responsible authority.
nonisolated struct Place: Sendable, Equatable {
    var countryCode: String?
    var state: String?
    var municipality: String?
    var district: String?
    var postalCode: String?
    var street: String?
    var houseNumber: String?

    /// One line for the chat, e.g. "Hauptstraße 12, 80331 München".
    var line: String {
        let street = [self.street, houseNumber].compactMap { $0 }.joined(separator: " ")
        let town = [postalCode, municipality].compactMap { $0 }.joined(separator: " ")
        return [street, town].filter { !$0.isEmpty }.joined(separator: ", ")
    }

    var isEmpty: Bool { municipality == nil && street == nil }
}

/// Turns a position into an address with the geocoder of the phone (MapKit, it works worldwide).
/// The coordinates go from the phone to Apple, our server gets only the text.
struct PlaceService {
    func place(for location: CLLocation) async -> Place? {
        // TODO: A timeout, the geocoder can take long without a network. Today a failure just means "no place".
        guard let request = MKReverseGeocodingRequest(location: location),
              let item = try? await request.mapItems.first
        else { return nil }
        let representations = item.addressRepresentations
        let place = Place(
            countryCode: representations?.region?.identifier,
            municipality: representations?.cityName,
            // MapKit gives a short address in one piece ("Hauptstraße 12"), no separate house number
            street: item.address?.shortAddress
        )
        return place.isEmpty ? nil : place
    }
}
