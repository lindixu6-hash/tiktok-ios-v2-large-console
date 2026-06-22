import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "position" {
    guard let event = CGEvent(source: nil) else {
        fail("failed to read mouse position")
    }
    let point = event.location
    print("OK:\(Int(point.x)),\(Int(point.y))")
    exit(0)
}

if CommandLine.arguments.count != 3 {
    fail("usage: mac_click <x> <y> | mac_click position")
}

guard let x = Double(CommandLine.arguments[1]), let y = Double(CommandLine.arguments[2]) else {
    fail("x and y must be numbers")
}

let point = CGPoint(x: x, y: y)
let source = CGEventSource(stateID: .hidSystemState)

if let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left) {
    move.post(tap: .cghidEventTap)
}

usleep(50_000)

guard let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
      let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
    fail("failed to create mouse events")
}

down.post(tap: .cghidEventTap)
usleep(80_000)
up.post(tap: .cghidEventTap)

print("OK:\(Int(x)),\(Int(y))")
