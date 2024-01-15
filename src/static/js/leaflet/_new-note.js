import { Tooltip } from "bootstrap"
import * as L from "leaflet"

const minZoom = 12

export const getNewNoteControl = () => {
    const control = new L.Control()

    // On zoomend, disable/enable button
    const onZoomEnd = () => {
        const map = control.map
        const button = control.button
        const tooltip = control.tooltip

        const currentZoom = map.getZoom()

        // Enable/disable buttons based on current zoom level
        if (currentZoom < minZoom) {
            if (!button.disabled) {
                button.disabled = true
                tooltip.setContent({
                    ".tooltip-inner": I18n.t("javascripts.site.createnote_disabled_tooltip"),
                })
            }
        } else {
            // biome-ignore lint/style/useCollapsedElseIf: Readability
            if (button.disabled) {
                button.disabled = false
                tooltip.setContent({
                    ".tooltip-inner": I18n.t("javascripts.site.createnote_tooltip"),
                })
            }
        }
    }

    control.onAdd = (map) => {
        if (control.map) console.error("NewNoteControl has already been added to a map")

        // Create container
        const container = document.createElement("div")

        // Create a button and a tooltip
        const button = document.createElement("button")
        button.className = "control-button"
        button.innerHTML = "<span class='icon note'></span>"

        const tooltip = new Tooltip(button, {
            title: I18n.t("javascripts.site.createnote_tooltip"),
            placement: "left",
            // TODO: check RTL support, also with leaflet options
        })

        control.button = button
        control.tooltip = tooltip
        control.map = map

        // Listen for events
        map.addEventListener("zoomend", onZoomEnd)

        // Initial update to set button states
        onZoomEnd()

        return container
    }

    return control
}
