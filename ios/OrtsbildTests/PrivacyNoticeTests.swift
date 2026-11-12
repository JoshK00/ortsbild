//
//  PrivacyNoticeTests.swift
//  OrtsbildTests
//

import Foundation
import Testing
@testable import Ortsbild

@MainActor
struct PrivacyNoticeTests {
    @Test func theSheetNamesWhatNotToPhotographAndPromisesNothingAboutTheCover() {
        let all = PrivacyNotice.sheetPoints.map { $0.title + " " + $0.text }.joined(separator: " ")
        #expect(all.contains("Personen") && all.contains("Kennzeichen") && all.contains("Dokumente"))
        // Not a word that lets people rely on the cover, and no extra remark about children
        #expect(!all.localizedCaseInsensitiveContains("automatisch"))
        #expect(!all.localizedCaseInsensitiveContains("Kindern"))
    }

    @Test func theReleaseTextSaysTheUserIsResponsibleWithAndWithoutPhoto() {
        #expect(PrivacyNotice.releaseWithPhoto.contains("niemand erkennbar"))
        #expect(PrivacyNotice.releaseWithPhoto.contains("verantwortlich"))
        #expect(PrivacyNotice.releaseWithoutPhoto.contains("verantwortlich"))
        #expect(PrivacyNotice.releaseWithoutPhoto.contains("Dashboard"))
    }

    @Test func theSheetHasThreeShortPoints() {
        #expect(PrivacyNotice.sheetPoints.count == 3)
        #expect(PrivacyNotice.sheetPoints.allSatisfy { $0.text.count < 120 })
    }

    @Test func theSheetOpensOnceAndNotAgainAfterTheButton() throws {
        let suite = "PrivacyNoticeTests-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let gate = PhotoNoticeGate(defaults: defaults)
        #expect(gate.shouldShow)
        gate.markSeen()
        #expect(!gate.shouldShow)
        #expect(!PhotoNoticeGate(defaults: defaults).shouldShow)
    }
}
