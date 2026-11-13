//
//  QuickReplyBarTests.swift
//  OrtsbildTests
//

import SwiftUI
import Testing
import UIKit
@testable import Ortsbild

@MainActor
struct QuickReplyBarTests {
    private let categories = ["Müll", "Schlagloch", "Straßenlaterne", "Spielgerät", "Graffiti", "Baum", "Etwas anderes"]

    private func size(of options: [String], width: CGFloat) -> CGSize {
        let host = UIHostingController(rootView: QuickReplyBar(options: options, isEnabled: true) { _ in })
        return host.sizeThatFits(in: CGSize(width: width, height: .greatestFiniteMagnitude))
    }

    @Test func manyRepliesMoveToTheNextLineAndStayInsideTheWidth() {
        let narrow = size(of: categories, width: 320)
        let wide = size(of: categories, width: 3000)
        #expect(narrow.width <= 320)
        #expect(narrow.height > wide.height)  // more than one line
    }

    @Test func aReplyIsNeverBrokenIntoLetters() {
        // One line of a pill is about 44 pt high. If a word broke after every letter, the block would be many times higher.
        let one = size(of: ["Straßenlaterne"], width: 320)
        #expect(one.height < 60)
        let all = size(of: categories, width: 320)
        #expect(all.height < 7 * 44)  // 7 replies, never one line each
    }

    @Test func fewRepliesStayOnOneLine() {
        let wide = size(of: ["Ja", "Nein"], width: 320)
        let single = size(of: ["Ja"], width: 320)
        #expect(wide.height == single.height)
    }
}
