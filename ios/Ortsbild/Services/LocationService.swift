//
//  LocationService.swift
//  Ortsbild
//

import CoreLocation

enum LocationError: Error {
    /// The user did not allow the location (or turned it off for the whole phone).
    case denied
    /// No usable position within the time limit.
    case unavailable
}

/// One position fix for a report. The location is mandatory in the report, there is no report without it.
struct LocationService {
    /// Worse than this (in meters) is too vague to find the defect.
    private let requiredAccuracy: CLLocationAccuracy = 100
    private let timeout: Duration = .seconds(20)

    func currentLocation() async throws -> CLLocation {
        // Asks for the permission the first time, and keeps the permission active while we wait
        let serviceSession = CLServiceSession(authorization: .whenInUse)
        defer { serviceSession.invalidate() }

        return try await withThrowingTaskGroup(of: CLLocation.self) { group in
            let accuracy = requiredAccuracy
            group.addTask {
                for try await update in CLLocationUpdate.liveUpdates() {
                    if update.authorizationDenied || update.authorizationDeniedGlobally { throw LocationError.denied }
                    if let location = update.location, location.horizontalAccuracy >= 0, location.horizontalAccuracy <= accuracy {
                        return location
                    }
                }
                throw LocationError.unavailable
            }
            let limit = timeout
            group.addTask {
                try await Task.sleep(for: limit)
                throw LocationError.unavailable
            }
            defer { group.cancelAll() }
            guard let location = try await group.next() else { throw LocationError.unavailable }
            return location
        }
    }
}
