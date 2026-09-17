import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("centric_gym_core_reception", {
    steps: () => [
        {
            content: "Search the member by name",
            trigger: ".o_gym_reception_search",
            run: "edit Tour Visitor",
        },
        {
            content: "Pick the member",
            trigger: ".o_gym_reception_results button:contains(Tour Visitor)",
            run: "click",
        },
        {
            content: "The member is checked in",
            trigger: ".o_gym_reception_card .card-header:contains(Checked in)",
        },
        {
            content: "The member is listed as inside",
            trigger: ".o_gym_reception_inside li:contains(Tour Visitor)",
        },
        {
            content: "A member without a membership is refused",
            trigger: ".o_gym_reception_search",
            run: "edit Tour Lapsed",
        },
        {
            trigger: ".o_gym_reception_results button:contains(Tour Lapsed)",
            run: "click",
        },
        {
            content: "Refused, with the reason",
            trigger: ".o_gym_reception_card .card-header:contains(Refused):contains(No membership)",
        },
        {
            content: "A manager can override",
            trigger: ".o_gym_reception_card button:contains(Override)",
            run: "click",
        },
        {
            trigger: ".o_gym_reception_card input",
            run: "edit Paying at the desk",
        },
        {
            trigger: ".o_gym_reception_card button:contains(Let In):enabled",
            run: "click",
        },
        {
            content: "Let in by override",
            trigger: ".o_gym_reception_card .card-header:contains(Let in by override)",
        },
        {
            content: "Check the first member out from the inside list",
            trigger: ".o_gym_reception_inside li:contains(Tour Visitor) button",
            run: "click",
        },
        {
            content: "Only the overridden member is left inside",
            trigger: ".o_gym_reception_inside:not(:has(li:contains(Tour Visitor))):has(li:contains(Tour Lapsed))",
        },
    ],
});
