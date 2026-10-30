import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PC3
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    property var displays: []
    property bool supported: false
    property bool busy: false
    property bool resetPending: false
    property bool hasError: false
    property bool preserveErrorOnRefresh: false
    property string message: "Loading displays…"
    property string activeCommand: ""
    property string activeOperation: ""
    property var pendingCommands: []

    Plasmoid.icon: "io.github.vivid.DisplaySaturation"
    toolTipMainText: "Vivid Saturation Controls"
    toolTipSubText: displays.map(function(view) {
        return view.display.output_name + " " + formatPercent(view.preferred_saturation)
    }).join(" · ")
    switchWidth: Kirigami.Units.gridUnit * 14
    switchHeight: Kirigami.Units.gridUnit * 8

    function formatPercent(value) {
        if (value === 0) {
            return "0%"
        }
        return (value > 0 ? "+" : "") + value + "%"
    }

    function run(command, operation, stableId, value) {
        if (operation === "set") {
            for (var index = 0; index < pendingCommands.length; index++) {
                if (pendingCommands[index].operation === "set"
                        && pendingCommands[index].stableId === stableId) {
                    pendingCommands[index] = {
                        command: command,
                        operation: operation,
                        stableId: stableId,
                        value: value
                    }
                    return
                }
            }
        } else if (operation === "list") {
            if (activeOperation === "list") {
                return
            }
            for (var queued = 0; queued < pendingCommands.length; queued++) {
                if (pendingCommands[queued].operation === "list") {
                    return
                }
            }
        }

        pendingCommands.push({
            command: command,
            operation: operation,
            stableId: stableId || "",
            value: value
        })
        executeNext()
    }

    function executeNext() {
        if (activeCommand.length || pendingCommands.length === 0) {
            busy = activeCommand.length > 0 || pendingCommands.length > 0
            return
        }
        var next = pendingCommands.shift()
        activeCommand = next.command
        activeOperation = next.operation
        busy = true
        commandSource.connectSource(next.command)
    }

    function commandFor(arguments) {
        return "PATH=\"$HOME/.local/bin:$HOME/bin:"
            + "$HOME/.local/share/vivid/venv/bin:/usr/local/bin:/usr/bin:$PATH\" "
            + "vivid " + arguments
    }

    function refreshDisplays() {
        run(commandFor("list --json"), "list")
    }

    function setSaturation(stableId, value) {
        if (!/^[A-Za-z0-9._-]+$/.test(stableId)) {
            message = "This display has an unsafe identity and cannot be selected here."
            hasError = true
            return
        }
        var percent = Math.round(value)
        message = "Applying " + formatPercent(percent) + " to the selected display…"
        hasError = false
        run(
            commandFor("set " + stableId + " " + percent + " --json"),
            "set",
            stableId,
            percent
        )
    }

    function resetAll() {
        if (resetPending || !supported || displays.length === 0) {
            return
        }
        resetPending = true
        hasError = false
        message = "Restoring the original profiles for Vivid-managed displays…"
        run(commandFor("reset --all --json"), "reset")
    }

    function openVivid() {
        run(commandFor("gui --detach --json"), "launch")
    }

    function handleCommand(sourceName, data) {
        if (sourceName !== activeCommand) {
            commandSource.disconnectSource(sourceName)
            return
        }

        var operation = activeOperation
        var succeeded = Number(data["exit code"]) === 0
        var output = data.stdout || ""
        var result = null
        var parseError = ""
        if (output.length > 0) {
            try {
                result = JSON.parse(output)
            } catch (error) {
                parseError = "Vivid returned invalid JSON: " + error
            }
        }

        commandSource.disconnectSource(sourceName)
        activeCommand = ""
        activeOperation = ""

        if (operation === "list") {
            if (succeeded && result && result.ok) {
                displays = result.displays || []
                supported = Boolean(result.supported)
                if (preserveErrorOnRefresh) {
                    preserveErrorOnRefresh = false
                } else {
                    hasError = false
                    message = supported
                        ? (displays.length ? "" : "No connected displays")
                        : "The current display backend is unsupported."
                }
            } else {
                message = result && result.error
                    ? result.error.message
                    : (parseError || data.stderr || "Could not read Vivid display status.")
                hasError = true
            }
        } else if (operation === "set") {
            if (succeeded && result && result.ok) {
                message = ""
                hasError = false
                preserveErrorOnRefresh = false
            } else {
                message = result && result.error
                    ? result.error.message
                    : (parseError || data.stderr || "The saturation change failed.")
                hasError = true
                preserveErrorOnRefresh = true
            }
            refreshDisplays()
        } else if (operation === "reset") {
            resetPending = false
            if (succeeded && result && result.ok) {
                message = ""
                hasError = false
                preserveErrorOnRefresh = false
            } else if (result && result.results) {
                var failures = result.results.filter(function(item) {
                    return !item.success
                }).map(function(item) {
                    var outputName = item.display ? item.display.output_name : "Display"
                    return outputName + ": " + item.message
                })
                message = failures.length
                    ? failures.join(" · ")
                    : "No Vivid-managed display needed resetting."
                hasError = failures.length > 0
                preserveErrorOnRefresh = hasError
            } else {
                message = result && result.error
                    ? result.error.message
                    : (parseError || data.stderr || "Could not reset the displays.")
                hasError = true
                preserveErrorOnRefresh = true
            }
            refreshDisplays()
        } else if (operation === "launch") {
            if (succeeded && result && result.ok) {
                message = ""
                hasError = false
            } else {
                message = result && result.error
                    ? result.error.message
                    : (parseError || data.stderr || "Could not open Vivid.")
                hasError = true
            }
        }

        executeNext()
    }

    Plasma5Support.DataSource {
        id: commandSource
        engine: "executable"
        connectedSources: []
        onNewData: function(sourceName, data) {
            root.handleCommand(sourceName, data)
        }
    }

    Component.onCompleted: refreshDisplays()
    onExpandedChanged: if (expanded) refreshDisplays()

    compactRepresentation: PC3.ToolButton {
        padding: 0
        icon.name: "io.github.vivid.DisplaySaturation"
        icon.width: Kirigami.Units.iconSizes.large
        icon.height: Kirigami.Units.iconSizes.large
        Accessible.name: "Open Vivid per-display saturation controls"
        onClicked: root.expanded = !root.expanded
    }

    fullRepresentation: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing
        Layout.minimumWidth: Kirigami.Units.gridUnit * 20
        Layout.preferredWidth: Kirigami.Units.gridUnit * 22

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                text: "Display saturation"
                level: 3
                Layout.fillWidth: true
            }

            PC3.ToolButton {
                text: "Refresh"
                icon.name: "view-refresh"
                enabled: !root.busy
                onClicked: root.refreshDisplays()
            }
        }

        Repeater {
            model: root.displays

            delegate: RowLayout {
                id: displayRow
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                PC3.Label {
                    text: displayRow.modelData.display.output_name
                    font.bold: true
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                }

                PC3.Slider {
                    id: slider
                    from: -100
                    to: 100
                    stepSize: 1
                    value: displayRow.modelData.preferred_saturation
                    enabled: root.supported && displayRow.modelData.display.enabled
                    Accessible.name: "Saturation for "
                        + displayRow.modelData.display.friendly_name
                    Layout.fillWidth: true
                    onPressedChanged: if (!pressed) apply()
                    onMoved: if (!pressed) debounce.restart()

                    Timer {
                        id: debounce
                        interval: 300
                        onTriggered: slider.apply()
                    }

                    function apply() {
                        debounce.stop()
                        root.setSaturation(
                            displayRow.modelData.display.stable_id,
                            slider.value
                        )
                    }
                }

                PC3.Label {
                    text: root.formatPercent(Math.round(slider.value))
                    horizontalAlignment: Text.AlignRight
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                }
            }
        }

        PC3.Label {
            visible: root.displays.length === 0
            text: root.message || "No connected displays"
            opacity: 0.7
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing

            PC3.Label {
                text: root.message
                visible: root.hasError || root.busy
                opacity: 0.7
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            Item { Layout.fillWidth: true }

            PC3.Button {
                text: "Reset all to baseline"
                icon.name: "edit-undo"
                enabled: root.supported && root.displays.length > 0
                    && !root.resetPending
                onClicked: root.resetAll()
            }

            PC3.Button {
                text: "Open Vivid"
                enabled: !root.busy
                onClicked: root.openVivid()
            }
        }
    }
}
