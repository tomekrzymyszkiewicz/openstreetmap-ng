const messagesContainer = document.querySelector(".messages-container")
if (messagesContainer) {
    // Panel
    const toggleAllCheckbox = document.querySelector(".toggle-all-checkbox")
    const numSelectedSpan = document.querySelector(".num-selected")
    const markReadButton = document.querySelector(".mark-read-btn")
    const markUnreadButton = document.querySelector(".mark-unread-btn")
    const deleteButton = document.querySelector(".delete-btn")

    // Table
    const toggleCheckboxes = document.querySelectorAll(".toggle-checkbox")

    const messageIds = new Set()

    const refreshUi = () => {
        if (messageIds.size === 0) {
            toggleAllCheckbox.checked = false
            toggleAllCheckbox.indeterminate = false
            markReadButton.disabled = true
            markUnreadButton.disabled = true
            deleteButton.disabled = true
        } else {
            // messageIds.size > 0
            markReadButton.disabled = false
            markUnreadButton.disabled = false
            deleteButton.disabled = false

            if (messageIds.size < toggleCheckboxes.length) {
                toggleAllCheckbox.checked = false
                toggleAllCheckbox.indeterminate = true
            } else {
                toggleAllCheckbox.checked = true
                toggleAllCheckbox.indeterminate = false
            }
        }

        numSelectedSpan.textContent = messageIds.size
    }

    // Listen for panel events
    toggleAllCheckbox.on("change", () => {
        const checked = toggleAllCheckbox.checked
        for (const check of toggleCheckboxes) {
            check.checked = checked
            const id = check.dataset.messageId
            if (checked) messageIds.add(id)
            else messageIds.delete(id)
        }
        refreshUi()
    })

    for (const form of [
        markReadButton.closest("form"),
        markUnreadButton.closest("form"),
        deleteButton.closest("form"),
    ]) {
        form.on("submit", () => {
            const input = document.createElement("input")
            input.type = "hidden"
            input.name = "message_ids"
            input.value = JSON.stringify([...messageIds])
            form.append(input)
        })
    }

    // Listen for table events
    for (const check of toggleCheckboxes) {
        check.on("change", () => {
            const id = check.dataset.messageId
            const checked = check.checked
            if (checked) messageIds.add(id)
            else messageIds.delete(id)
            refreshUi()
        })
    }
}