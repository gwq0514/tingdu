import AppKit
let image=NSImage(size:NSSize(width:1024,height:1024))
image.lockFocus()
NSColor.white.setFill();NSBezierPath(roundedRect:NSRect(x:40,y:40,width:944,height:944),xRadius:216,yRadius:216).fill()
NSColor(calibratedRed:0.145,green:0.388,blue:0.922,alpha:1).setFill()
NSBezierPath(roundedRect:NSRect(x:110,y:110,width:804,height:804),xRadius:175,yRadius:175).fill()
NSColor.white.setFill()
for (i,h) in [170,300,430,300,170].enumerated(){NSBezierPath(roundedRect:NSRect(x:260+i*100,y:(1024-h)/2,width:56,height:h),xRadius:28,yRadius:28).fill()}
image.unlockFocus()
let bitmap=NSBitmapImageRep(data:image.tiffRepresentation!)!
try bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:CommandLine.arguments[1]))
