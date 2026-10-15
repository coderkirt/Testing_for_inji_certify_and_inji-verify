package io.mosip.certify.entity.attributes;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.io.Serializable;

@JsonInclude(JsonInclude.Include.NON_NULL)
// Null display fields are omitted so issuer metadata stays valid.
public class MetaDataDisplay implements Serializable {
    private Logo logo;
    private String name;
    private String locale;

    @JsonProperty("text_color")
    private String textColor;

    @JsonProperty("background_color")
    private String backgroundColor;

    @JsonProperty("background_image")
    private BackgroundImage backgroundImage;

    public MetaDataDisplay() {
    }

    public Logo getLogo() {
        return logo;
    }

    public void setLogo(Logo logo) {
        this.logo = logo;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getLocale() {
        return locale;
    }

    public void setLocale(String locale) {
        this.locale = locale;
    }

    public String getTextColor() {
        return textColor;
    }

    public void setTextColor(String textColor) {
        this.textColor = textColor;
    }

    public String getBackgroundColor() {
        return backgroundColor;
    }

    public void setBackgroundColor(String backgroundColor) {
        this.backgroundColor = backgroundColor;
    }

    public BackgroundImage getBackgroundImage() {
        return backgroundImage;
    }

    public void setBackgroundImage(BackgroundImage backgroundImage) {
        this.backgroundImage = backgroundImage;
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Logo implements Serializable {
        private String uri;

        @JsonProperty("alt_text")
        private String altText;

        public Logo() {
        }

        public String getUri() {
            return uri;
        }

        public void setUri(String uri) {
            this.uri = uri;
        }

        public String getAltText() {
            return altText;
        }

        public void setAltText(String altText) {
            this.altText = altText;
        }
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class BackgroundImage implements Serializable {
        private String uri;

        public BackgroundImage() {
        }

        public String getUri() {
            return uri;
        }

        public void setUri(String uri) {
            this.uri = uri;
        }
    }
}
