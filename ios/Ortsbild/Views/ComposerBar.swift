//
//  ComposerBar.swift
//  Ortsbild
//

import PhotosUI
import SwiftUI

/// Composer bar: attach menu, photo preview, text field and send button.
struct ComposerBar: View {
    @Binding var text: String
    @Binding var photo: UIImage?
    let canSend: Bool
    /// The hint in the empty input field, "Nachricht" unless a question waits for the answer.
    var placeholder: LocalizedStringKey = "Nachricht"
    let onSend: () -> Void

    @State private var showCamera = false
    @State private var showLibrary = false
    @State private var pickerItem: PhotosPickerItem?
    /// The first time, the sheet with the photo rules opens before the camera or the library. `pendingSource` is what the user wanted.
    @State private var showNotice = false
    @State private var pendingSource: Source?

    private enum Source { case camera, library }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let photo {
                photoPreview(photo)
            }

            HStack(alignment: .bottom, spacing: 8) {
                attachMenu

                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...4)
                    .padding(.vertical, 8)

                Button(action: onSend) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 32))
                }
                .disabled(!canSend)
                .accessibilityLabel("Senden")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .glassEffect(.regular, in: .rect(cornerRadius: 26))
        .padding(.horizontal, 12)
        .padding(.bottom, 4)
        .sheet(isPresented: $showNotice, onDismiss: openPendingSource) {
            PhotoNoticeSheet()
        }
        .photosPicker(isPresented: $showLibrary, selection: $pickerItem, matching: .images)
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { photo = $0 }
                .ignoresSafeArea()
        }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self),
                   let image = UIImage(data: data) {
                    photo = image
                }
                // TODO: Show an error to the user if loading the photo fails
                pickerItem = nil
            }
        }
    }

    /// Opens the source at once, or the sheet with the rules first if the user has not seen it yet.
    private func request(_ source: Source) {
        pendingSource = source
        let gate = PhotoNoticeGate()
        if gate.shouldShow {
            showNotice = true
        } else {
            openPendingSource()
        }
    }

    private func openPendingSource() {
        let source = pendingSource
        pendingSource = nil
        switch source {
        case .camera: showCamera = true
        case .library: showLibrary = true
        case nil: break
        }
    }

    private var attachMenu: some View {
        Menu {
            // TODO: The camera is unavailable in the simulator, show a hint instead of a disabled button
            Button {
                request(.camera)
            } label: {
                Label("Foto aufnehmen", systemImage: "camera")
            }
            .disabled(!CameraPicker.isAvailable)

            Button {
                request(.library)
            } label: {
                Label("Aus Mediathek wählen", systemImage: "photo.on.rectangle")
            }
        } label: {
            Image(systemName: "plus.circle.fill")
                .font(.system(size: 32))
                .foregroundStyle(.secondary)
        }
        .accessibilityLabel("Foto hinzufügen")
    }

    private func photoPreview(_ image: UIImage) -> some View {
        Image(uiImage: image)
            .resizable()
            .scaledToFill()
            .frame(width: 64, height: 64)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(alignment: .topTrailing) {
                Button {
                    photo = nil
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .symbolRenderingMode(.palette)
                        .foregroundStyle(.white, .black.opacity(0.6))
                }
                .offset(x: 6, y: -6)
                .accessibilityLabel("Foto entfernen")
            }
            .padding(.top, 6)
            .padding(.leading, 4)
            .accessibilityElement(children: .contain)
    }
}

#Preview {
    @Previewable @State var text = ""
    @Previewable @State var photo: UIImage?
    ComposerBar(text: $text, photo: $photo, canSend: true) {}
}
