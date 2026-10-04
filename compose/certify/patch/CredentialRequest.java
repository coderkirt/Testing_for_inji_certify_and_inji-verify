package io.mosip.certify.core.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import java.util.List;
import java.util.Map;
import java.util.Objects;

@JsonIgnoreProperties(ignoreUnknown = true)
public class CredentialRequest {

    @JsonProperty("credential_configuration_id")
    private String credentialConfigId;

    @JsonProperty("credential_identifier")
    private String credentialIdentifier;

    @Valid
    @NotEmpty(message = "invalid_proof")
    private Map<ProofType, List<String>> proofs;

    public String getCredentialConfigId() {
        return this.credentialConfigId;
    }

    public String getCredentialIdentifier() {
        return this.credentialIdentifier;
    }

    public Map<ProofType, List<String>> getProofs() {
        return this.proofs;
    }

    public void setCredentialConfigId(String credentialConfigId) {
        this.credentialConfigId = credentialConfigId;
    }

    public void setCredentialIdentifier(String credentialIdentifier) {
        this.credentialIdentifier = credentialIdentifier;
    }

    public void setProofs(Map<ProofType, List<String>> proofs) {
        this.proofs = proofs;
    }

    protected boolean canEqual(Object other) {
        return other instanceof CredentialRequest;
    }

    @Override
    public boolean equals(Object o) {
        if (o == this) {
            return true;
        }
        if (!(o instanceof CredentialRequest)) {
            return false;
        }
        CredentialRequest other = (CredentialRequest) o;
        if (!other.canEqual(this)) {
            return false;
        }
        return Objects.equals(this.getCredentialConfigId(), other.getCredentialConfigId())
                && Objects.equals(this.getProofs(), other.getProofs());
    }

    @Override
    public int hashCode() {
        return Objects.hash(this.getCredentialConfigId(), this.getProofs());
    }

    @Override
    public String toString() {
        return "CredentialRequest(credentialConfigId=" + this.getCredentialConfigId()
                + ", proofs=" + this.getProofs() + ")";
    }
}
