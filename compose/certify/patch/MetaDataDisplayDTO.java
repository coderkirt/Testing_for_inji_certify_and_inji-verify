package io.mosip.certify.core.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Objects;

@JsonInclude(JsonInclude.Include.NON_NULL)
// This DTO is what the well-known endpoint serializes. Null display fields are omitted.
public class MetaDataDisplayDTO {
    private Logo logo;
    private String name;
    private String locale;

    @JsonProperty("text_color")
    private String textColor;

    @JsonProperty("background_color")
    private String backgroundColor;

    @JsonProperty("background_image")
    private BackgroundImage backgroundImage;

    public MetaDataDisplayDTO() {
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

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof MetaDataDisplayDTO)) {
            return false;
        }
        MetaDataDisplayDTO that = (MetaDataDisplayDTO) other;
        return Objects.equals(logo, that.logo)
                && Objects.equals(name, that.name)
                && Objects.equals(locale, that.locale)
                && Objects.equals(textColor, that.textColor)
                && Objects.equals(backgroundColor, that.backgroundColor)
                && Objects.equals(backgroundImage, that.backgroundImage);
    }

    @Override
    public int hashCode() {
        return Objects.hash(logo, name, locale, textColor, backgroundColor, backgroundImage);
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Logo {
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

        @Override
        public boolean equals(Object other) {
            if (this == other) {
                return true;
            }
            if (!(other instanceof Logo)) {
                return false;
            }
            Logo logo = (Logo) other;
            return Objects.equals(uri, logo.uri) && Objects.equals(altText, logo.altText);
        }

        @Override
        public int hashCode() {
            return Objects.hash(uri, altText);
        }
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class BackgroundImage {
        private String uri;

        public BackgroundImage() {
        }

        public String getUri() {
            return uri;
        }

        public void setUri(String uri) {
            this.uri = uri;
        }

        @Override
        public boolean equals(Object other) {
            if (this == other) {
                return true;
            }
            if (!(other instanceof BackgroundImage)) {
                return false;
            }
            return Objects.equals(uri, ((BackgroundImage) other).uri);
        }

        @Override
        public int hashCode() {
            return Objects.hash(uri);
        }
    }
}
