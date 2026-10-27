package domain

// HasClassificationEvidence is a necessary admission condition, not a semantic
// accuracy estimate. A class prior or features equally common across classes
// must not authorize a suggestion. At least one query feature must occur in a
// strictly greater proportion of the predicted class's confirmed samples than
// in every competing class. Normalize by sample count, not raw occurrences, so
// duplicating a class's history cannot turn shared metadata into evidence.
func HasClassificationEvidence(samples []TrainingSample, query []string, category string) bool {
	classSizes := map[string]int{}
	presence := map[string]map[string]int{}
	wanted := map[string]bool{}
	for _, feature := range query {
		wanted[feature] = true
	}
	for _, sample := range samples {
		classSizes[sample.CategoryID]++
		if presence[sample.CategoryID] == nil {
			presence[sample.CategoryID] = map[string]int{}
		}
		seen := map[string]bool{}
		for _, feature := range sample.Features {
			if wanted[feature] && !seen[feature] {
				presence[sample.CategoryID][feature]++
				seen[feature] = true
			}
		}
	}
	if len(classSizes) < 2 || classSizes[category] == 0 {
		return false
	}
	for feature := range wanted {
		support := presence[category][feature]
		if support == 0 {
			continue
		}
		distinguishes := true
		for other, count := range classSizes {
			if other != category && support*count <= presence[other][feature]*classSizes[category] {
				distinguishes = false
				break
			}
		}
		if distinguishes {
			return true
		}
	}
	return false
}
