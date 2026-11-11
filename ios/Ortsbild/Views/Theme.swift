//
//  Theme.swift
//  Ortsbild
//

import SwiftUI

/// The look of the app, the same as the dashboard: dark ground, frosted glass, white as the accent.
/// Everything that is shared lives here, so a color or a corner is changed in one place.
enum Theme {
    /// The dark ink: text on a white button, the dark rim of a white badge (`--badge-fg` of the dashboard).
    static let ink = Color(red: 0.07, green: 0.086, blue: 0.114)
    /// The ground of every screen.
    static let canvas = Color(red: 0.06, green: 0.065, blue: 0.07)
    /// A pane of frosted glass: a light veil over the material, with a fine rim.
    static let glassFill = Color.white.opacity(0.12)
    static let glassRim = Color.white.opacity(0.26)
}

/// The ground of the screens: dark, with a soft light from above and a vignette at the edges (like the map of the dashboard).
struct AppBackground: View {
    var body: some View {
        ZStack {
            Theme.canvas
            RadialGradient(
                colors: [Color(red: 0.20, green: 0.24, blue: 0.21).opacity(0.75), .clear],
                center: .init(x: 0.5, y: 0.18),
                startRadius: 10,
                endRadius: 520
            )
            // The vignette: dark edges
            RadialGradient(
                colors: [.clear, Color.black.opacity(0.55)],
                center: .center,
                startRadius: 260,
                endRadius: 760
            )
        }
        .ignoresSafeArea()
    }
}

extension View {
    /// A pane of frosted glass with a fine rim, for cards and tiles.
    func glassCard(cornerRadius: CGFloat = 20) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        return self
            .background(Theme.glassFill, in: shape)
            .background(.ultraThinMaterial, in: shape)
            .overlay(shape.stroke(Theme.glassRim, lineWidth: 1))
    }
}

/// The main button: white with dark text (the white marker of the dashboard).
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(Theme.ink)
            .padding(.vertical, 14)
            .padding(.horizontal, 18)
            .background(Color.white.opacity(isEnabled ? (configuration.isPressed ? 0.8 : 1) : 0.4), in: Capsule())
    }
}

/// The second button: frosted glass with white text. A destructive button has red text.
struct GlassButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.medium))
            .foregroundStyle(configuration.role == .destructive ? Color(red: 1, green: 0.42, blue: 0.42) : Color.white)
            .padding(.vertical, 10)
            .padding(.horizontal, 16)
            .glassCard(cornerRadius: 22)
            .opacity(isEnabled ? (configuration.isPressed ? 0.7 : 1) : 0.45)
    }
}
