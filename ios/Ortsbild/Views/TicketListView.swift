//
//  TicketListView.swift
//  Ortsbild
//

import SwiftUI

/// The start screen: one row per report, newest on top, and a button for a new report.
/// Every report has its own chat, so one problem never mixes with another.
struct TicketListView: View {
    @Environment(TicketStore.self) private var store
    @Environment(AuthViewModel.self) private var auth
    @State private var path: [UUID] = []

    // TODO: Move texts into a String Catalog (localization), German only for now

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if store.tickets.isEmpty {
                    emptyState
                } else {
                    list
                }
            }
            .navigationTitle("Meldungen")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        auth.isSheetPresented = true
                    } label: {
                        Image(systemName: auth.isSignedIn ? "person.crop.circle.fill" : "person.crop.circle")
                    }
                    .accessibilityLabel("Konto")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: newReport) {
                        Image(systemName: "square.and.pencil")
                    }
                    .accessibilityLabel("Neue Meldung")
                }
            }
            .navigationDestination(for: UUID.self) { id in
                ChatView(ticketID: id, store: store)
            }
        }
    }

    private var list: some View {
        List {
            ForEach(store.tickets) { ticket in
                NavigationLink(value: ticket.id) {
                    TicketRow(ticket: ticket)
                }
            }
            .onDelete { offsets in
                let ids = offsets.map { store.tickets[$0].id }
                ids.forEach(store.delete)
            }
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("Noch keine Meldungen", systemImage: "tray")
        } description: {
            Text("Für jedes Problem gibt es eine eigene Meldung mit eigenem Verlauf. Der Verlauf bleibt nur auf diesem iPhone.")
        } actions: {
            Button("Neue Meldung", action: newReport)
                .buttonStyle(.borderedProminent)
        }
    }

    private func newReport() {
        path.append(store.newTicketID())
    }
}

private struct TicketRow: View {
    let ticket: Ticket

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(ticket.title)
                    .font(.headline)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(ticket.updatedAt, format: .dateTime.day().month().hour().minute())
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Text(ticket.preview)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    TicketListView()
        .environment(TicketStore.preview)
        .environment(AuthViewModel(service: MockAuthService()))
}
