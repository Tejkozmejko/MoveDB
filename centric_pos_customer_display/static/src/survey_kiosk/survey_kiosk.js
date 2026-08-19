import { patch } from "@web/core/utils/patch";
import { redirect } from "@web/core/utils/urls";
import { SurveyForm } from "@survey/interactions/survey_form";

/**
 * Kiosk mode for door tablets.
 *
 * A customer walking out will not read a start screen, will not press "Submit" and
 * will certainly not answer "Are you sure?". So on a kiosk survey we start on the
 * questions, a tap on an answer IS the answer, and the survey resets itself.
 *
 * Everything is behind `centric_kiosk_mode`, so regular surveys are untouched.
 */
patch(SurveyForm.prototype, {
    setup() {
        super.setup();
        const formEl = this.el.querySelector("form.o_survey-fill-form");
        this.centricKiosk = formEl?.dataset.centricKiosk === "1";
        this.centricKioskToken = formEl?.dataset.surveyToken;
        this.centricKioskDelay = (parseInt(formEl?.dataset.centricKioskDelay, 10) || 3) * 1000;
        if (this.centricKiosk) {
            document.body.classList.add("o_centric_kiosk");
        }
    },

    start() {
        const result = super.start(...arguments);
        if (this.centricKiosk) {
            if (this.options.isStartScreen) {
                // Skip the "Start Survey" splash: the tablet must always show the faces.
                this.waitForTimeout(() => this.submitForm({}), 0);
            } else if (this.el.querySelector(".o_survey_finished")) {
                // Reached on a reload of an already answered page.
                this.centricKioskScheduleReset();
            }
        }
        return result;
    },

    /**
     * The next screen is injected in place, so this is where we catch the thank you page.
     */
    onNextScreenDone(options) {
        const result = super.onNextScreenDone(options);
        if (this.centricKiosk && this.el.querySelector(".o_survey_finished")) {
            this.centricKioskScheduleReset();
        }
        return result;
    },

    /**
     * Native only auto-continues when the question is not the last one, which on a
     * one question survey means never. On a kiosk the tap must submit.
     */
    async onChoiceItemChange(ev) {
        const result = await super.onChoiceItemChange(ev);
        if (this.centricKiosk && !this.readonly && this.el.querySelector("button[value='finish']")) {
            await this.submitForm({ isFinish: true });
        }
        return result;
    },

    /**
     * Skip the "Are you sure you want to submit the survey?" dialog: nobody is there
     * to confirm it.
     */
    onSubmit(ev) {
        if (this.centricKiosk && ev.currentTarget.value === "finish") {
            ev.preventDefault();
            this.submitForm({ isFinish: true });
            return;
        }
        return super.onSubmit(ev);
    },

    /**
     * Tapping a face must select it, not open the image zoomer.
     */
    onChoiceImageClick(ev) {
        if (this.centricKiosk) {
            return;
        }
        return super.onChoiceImageClick(ev);
    },

    centricKioskScheduleReset() {
        if (this.centricKioskResetting) {
            return;
        }
        this.centricKioskResetting = true;
        this.waitForTimeout(
            () => redirect(`/survey/start/${this.centricKioskToken}`),
            this.centricKioskDelay
        );
    },
});
