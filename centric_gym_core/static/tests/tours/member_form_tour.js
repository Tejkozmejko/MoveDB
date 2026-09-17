import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("centric_gym_core_member_form", {
    steps: () => [
        {
            content: "Open the member from the Members kanban",
            trigger: ".o_kanban_record:contains(Tour Member)",
            run: "click",
        },
        {
            content: "Open the Gym tab",
            trigger: ".o_notebook .nav-link:contains(Gym)",
            run: "click",
        },
        {
            content: "The member has a 4-digit PIN (editable, the tour runs as a gym manager)",
            trigger: ".o_notebook .o_field_widget[name=gym_pin] input",
            run() {
                if (!/^[0-9]{4}$/.test(this.anchor.value)) {
                    throw new Error(`Expected a 4-digit PIN, got "${this.anchor.value}"`);
                }
            },
        },
        {
            content: "Open the camera",
            trigger: ".o_gym_photo_btn",
            run: "click",
        },
        {
            content: "The camera dialog opens (a headless browser has no camera)",
            trigger: ".modal .o_gym_photo_dialog",
        },
        {
            content: "Close it",
            trigger: ".modal-footer button:contains(Cancel)",
            run: "click",
        },
        {
            content: "The dialog is gone",
            trigger: "body:not(:has(.o_gym_photo_dialog))",
        },
    ],
});
