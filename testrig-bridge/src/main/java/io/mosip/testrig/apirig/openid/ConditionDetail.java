package io.mosip.testrig.apirig.openid;

/**
 * One conformance condition that was unexpected, expected, or expected but
 * absent. Carries the block name so a reader can see which part of the flow
 * produced it without opening the suite.
 */
public class ConditionDetail {
    public String currentBlock;
    public String src;

    public ConditionDetail() {
    }

    public ConditionDetail(String currentBlock, String src) {
        this.currentBlock = currentBlock;
        this.src = src;
    }

    @Override
    public String toString() {
        String block = currentBlock == null || currentBlock.isBlank() ? "(no block)" : currentBlock;
        return block + " / " + src;
    }
}
