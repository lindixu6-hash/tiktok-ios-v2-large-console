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

if CommandLine.arguments.count == 7 && CommandLine.arguments[1] == "drag" {
    guard let startX = Double(CommandLine.arguments[2]),
          let startY = Double(CommandLine.arguments[3]),
          let endX = Double(CommandLine.arguments[4]),
          let endY = Double(CommandLine.arguments[5]),
          let duration = Double(CommandLine.arguments[6]) else {
        fail("drag coordinates and duration must be numbers")
    }

    let source = CGEventSource(stateID: .hidSystemState)
    let start = CGPoint(x: startX, y: startY)
    let end = CGPoint(x: endX, y: endY)
    let safeDuration = max(0.05, duration)
    let holdBeforeMove: useconds_t = 40_000
    let releaseAfterEnd: useconds_t = 20_000
    let totalSteps = 12
    let stepDelay = useconds_t(max(2000, Int(safeDuration * 1_000_000 / Double(totalSteps))))

    guard let down = CGEvent(
        mouseEventSource: source,
        mouseType: .leftMouseDown,
        mouseCursorPosition: start,
        mouseButton: .left
    ) else {
        fail("failed to create drag down event")
    }

    down.post(tap: .cghidEventTap)
    usleep(holdBeforeMove)

    for step in 1...totalSteps {
        let t = Double(step) / Double(totalSteps)
        let ease = t * t * (3 - 2 * t)
        let point = CGPoint(
            x: startX + (endX - startX) * ease,
            y: startY + (endY - startY) * ease
        )
        guard let drag = CGEvent(
            mouseEventSource: source,
            mouseType: .leftMouseDragged,
            mouseCursorPosition: point,
            mouseButton: .left
        ) else {
            fail("failed to create drag event")
        }
        drag.post(tap: .cghidEventTap)
        if step < totalSteps {
            usleep(stepDelay)
        }
    }

    usleep(releaseAfterEnd)

    guard let up = CGEvent(
        mouseEventSource: source,
        mouseType: .leftMouseUp,
        mouseCursorPosition: end,
        mouseButton: .left
    ) else {
        fail("failed to create drag end event")
    }
    up.post(tap: .cghidEventTap)

    print("OK:DRAG:\(Int(startX)),\(Int(startY))->\(Int(endX)),\(Int(endY))")
    exit(0)
}

if CommandLine.arguments.count >= 4 && CommandLine.arguments[1] == "flick" {
    guard let totalDelta = Double(CommandLine.arguments[2]),
          let steps = Int(CommandLine.arguments[3]),
          let durationMs = Int(CommandLine.arguments[4]) else {
        fail("flick arguments: <total_delta_y> <steps> <duration_ms>")
    }
    let safeSteps = max(6, min(30, steps))
    let safeDuration = max(50, min(500, durationMs))
    let stepUs = useconds_t(safeDuration * 1000 / safeSteps)
    let source = CGEventSource(stateID: .hidSystemState)

    for step in 1...safeSteps {
        let t = Double(step) / Double(safeSteps)
        let velocity = sin((1.0 - t) * Double.pi / 2)
        let stepDelta = Int32((totalDelta / Double(safeSteps)) * velocity * 1.8)
        guard let event = CGEvent(
            scrollWheelEvent2Source: source,
            units: .pixel,
            wheelCount: 1,
            wheel1: stepDelta,
            wheel2: 0,
            wheel3: 0
        ) else {
            fail("failed to create flick scroll event")
        }
        event.post(tap: .cghidEventTap)
        if step < safeSteps {
            usleep(stepUs)
        }
    }
    print("OK:FLICK:\(Int(totalDelta)):\(safeSteps):\(safeDuration)")
    exit(0)
}

if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "scroll" {
    guard let deltaY = Double(CommandLine.arguments[2]) else {
        fail("scroll delta must be a number")
    }
    let source = CGEventSource(stateID: .hidSystemState)
    guard let event = CGEvent(
        scrollWheelEvent2Source: source,
        units: .pixel,
        wheelCount: 1,
        wheel1: Int32(deltaY),
        wheel2: 0,
        wheel3: 0
    ) else {
        fail("failed to create scroll event")
    }
    event.post(tap: .cghidEventTap)
    print("OK:SCROLL:\(Int(deltaY))")
    exit(0)
}

if CommandLine.arguments.count != 3 {
    fail("usage: mac_click <x> <y> | mac_click position | mac_click drag <sx> <sy> <ex> <ey> <dur> | mac_click flick <delta> <steps> <ms> | mac_click scroll <delta_y>")
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
