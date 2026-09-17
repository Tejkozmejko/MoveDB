import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

// image_1920 is scaled down to 1920px on the server anyway.
const MAX_EDGE = 1920;
const JPEG_QUALITY = 0.85;

/**
 * Live webcam preview with a capture button. It owns the camera stream and
 * stops it when it closes, however it was closed.
 */
export class GymMemberPhotoDialog extends Component {
    static template = "centric_gym_core.MemberPhotoDialog";
    static components = { Dialog };
    static props = {
        onCapture: Function,
        close: Function,
    };

    setup() {
        this.videoRef = useRef("video");
        this.state = useState({ ready: false, error: "" });
        this.stream = null;

        onMounted(async () => {
            if (!navigator.mediaDevices?.getUserMedia) {
                // Browsers only expose cameras on https (or localhost).
                this.state.error = _t("This browser only allows the camera on a secure (https) connection.");
                return;
            }
            try {
                this.stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: { ideal: "user" } },
                    audio: false,
                });
            } catch {
                this.state.error = _t("No camera was found, or access to it was refused.");
                return;
            }
            if (this.videoRef.el) {
                this.videoRef.el.srcObject = this.stream;
                await this.videoRef.el.play().catch(() => {});
                this.state.ready = true;
            }
        });

        onWillUnmount(() => this.stopStream());
    }

    get title() {
        return _t("Member Photo");
    }

    stopStream() {
        this.stream?.getTracks().forEach((track) => track.stop());
        this.stream = null;
    }

    capture() {
        const video = this.videoRef.el;
        if (!video || !this.state.ready) {
            return;
        }
        const scale = Math.min(1, MAX_EDGE / Math.max(video.videoWidth, video.videoHeight));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        // Drawn from the video itself, so the mirrored preview does not end up
        // mirrored on the card.
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        // Binary fields take plain base64, without the data: prefix.
        const base64 = canvas.toDataURL("image/jpeg", JPEG_QUALITY).split(",")[1];
        this.stopStream();
        this.props.onCapture(base64);
        this.props.close();
    }
}

/**
 * "Take Photo" button on the member's Gym tab. The standard image field only
 * opens a file picker; at the desk the photo is taken there and then.
 */
export class GymMemberPhotoWidget extends Component {
    static template = "centric_gym_core.MemberPhotoWidget";
    static props = { ...standardWidgetProps };

    setup() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
    }

    openCamera() {
        this.dialog.add(GymMemberPhotoDialog, {
            onCapture: async (base64) => {
                await this.props.record.update({ image_1920: base64 });
                this.notification.add(_t("Photo taken. Save the contact to keep it."), {
                    type: "success",
                });
            },
        });
    }
}

registry.category("view_widgets").add("centric_gym_core_member_photo", {
    component: GymMemberPhotoWidget,
});
