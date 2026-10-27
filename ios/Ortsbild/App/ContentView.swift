//
//  ContentView.swift
//  Ortsbild
//
//  Created by Joshua Kehrer on 26.10.26.
//

import SwiftUI

struct ContentView: View {
    var body: some View {
        ChatView()
    }
}

#Preview {
    ContentView()
        .environment(AuthViewModel())
}
