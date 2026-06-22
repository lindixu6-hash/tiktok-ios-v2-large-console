import CoreGraphics
import Foundation

final class Recorder {
    var clicks: [(x: Int, y: Int, ms: Int)] = []
    let startedAt = CFAbsoluteTimeGetCurrent()
    let timeoutAt: CFAbsoluteTime
    let stopPath: String?

    init(timeoutSeconds: Double, stopPath: String?) {
        self.timeoutAt = startedAt + timeoutSeconds
        self.stopPath = stopPath
    }

    func addClick(_ point: CGPoint) {
        let ms = Int((CFAbsoluteTimeGetCurrent() - startedAt) * 1000)
        clicks.append((x: Int(point.x), y: Int(point.y), ms: ms))
        writeLine("CLICK:\(Int(point.x)),\(Int(point.y)),\(ms)")
    }

    func finish(_ reason: String) -> Never {
        writeLine("DONE:\(reason):\(clicks.count)")
        exit(0)
    }
}

func writeLine(_ message: String) {
    FileHandle.standardOutput.write((message + "\n").data(using: .utf8)!)
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

let timeout = CommandLine.arguments.count >= 2 ? (Double(CommandLine.arguments[1]) ?? 30.0) : 30.0
let stopPath = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : nil
let recorder = Recorder(timeoutSeconds: timeout, stopPath: stopPath)

let mask =
    (1 << CGEventType.leftMouseDown.rawValue) |
    (1 << CGEventType.rightMouseDown.rawValue) |
    (1 << CGEventType.keyDown.rawValue)

let callback: CGEventTapCallBack = { _, type, event, userInfo in
    guard let userInfo else {
        return Unmanaged.passUnretained(event)
    }

    let recorder = Unmanaged<Recorder>.fromOpaque(userInfo).takeUnretainedValue()

    if CFAbsoluteTimeGetCurrent() >= recorder.timeoutAt {
        recorder.finish("timeout")
    }

    if type == .leftMouseDown {
        recorder.addClick(event.location)
    } else if type == .rightMouseDown {
        recorder.finish("right_click")
    } else if type == .keyDown {
        let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
        if keyCode == 53 {
            recorder.finish("escape")
        }
    }

    return Unmanaged.passUnretained(event)
}

guard let eventTap = CGEvent.tapCreate(
    tap: .cgSessionEventTap,
    place: .headInsertEventTap,
    options: .listenOnly,
    eventsOfInterest: CGEventMask(mask),
    callback: callback,
    userInfo: Unmanaged.passUnretained(recorder).toOpaque()
) else {
    fail("failed to create event tap; grant Accessibility permission to Terminal or Trae CN")
}

let runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, eventTap, 0)
CFRunLoopAddSource(CFRunLoopGetCurrent(), runLoopSource, .commonModes)
CGEvent.tapEnable(tap: eventTap, enable: true)

DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
    recorder.finish("timeout")
}

DispatchQueue.global().async {
    while true {
        if let stopPath = recorder.stopPath, FileManager.default.fileExists(atPath: stopPath) {
            recorder.finish("stop_file")
        }
        usleep(100_000)
    }
}

CFRunLoopRun()
