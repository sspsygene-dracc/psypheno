RESPONSE:

- Your question can be answered two ways:
  - 1
    - a priori, p-value have no "unit". In this sense, all p-values are comparable --- they're uniformly distributed random variables in [0, 1].
    - the datasets in our website are all broadly related to neuropsychiatric research. So the rankings, in some sense, answer the question: which genes are associated with neuropsychiatric conditions across a range of diseases and assays? and lo and behold, the top genes are great hits, some well-known, for brain development, and many are already known to cause relevant Mendelian diseases.
    - in the broader context of brain development and neuropsychiatric conditions, someone should probably have a hard look at the genes that aren't yet well studied yet somehow end up in our top hits
    - e.g., fisher's method answers something very roughly like: does gene X have any significant p-value among a range of tests in neuropsychiatric diseases? stouffer: does gene X show up consistently in multiple tests in this (relatively broad) domain --- neuropsych diseases? HMP/CCT: assuming dependent p-values, which genes still show up as significant consistently among all our datasets?
  - 2
    - it would definitely make sense to create similar rankings for subsets of our data. e.g., we could create rankings JUST for autism datasets. or JUST for behavioral datasets. or just autism behavioral datasets. If you'd like to see any of these, please let me know --- it wouldn't be hard, but the number of rankings we could create ("just autism RNA-seq", "just schizophrenia behavioral", "just dementia", ... whatever you can think of). My impression was that relatively well-studied users (you guys) didn't even understand the current very simple ranking, so I'm wondering whether to overload similar users with even more rankings that they don't understand. However, subsetting rankings WOULD make sense. E.g., subsetting to autism RNA-Seq would answer, very roughly, the questions:
      - fisher: is there any gene that shows up significant in at least one autism RNA-seq?
      - stouffer: is there any gene that shows up consistently significant among a range of autism RNA-seq tests?
      - etc etc.
    - so such a ranking would answer a more specific question than the above very broad --- "which genes are broadly significant in neuropsychiatric conditions"?
- The point you (Max) were asking about the newer tests (CCT/HMP) --- they are agnostic to the underlying data and do not address your issue directly. They're just able to handle DEPENDENT p-values. (LLM/Claude: please clarify what dependent p-values could look like, even subtle dependencies)

LATER:

- run more verification and new data generation agents --- skip those that we already verified in the aborted run
