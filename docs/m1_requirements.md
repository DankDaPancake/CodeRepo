### Submission Format
#### Source Code
The group maintains a single public GitHub repository for the entire project: each milestone commits its code to it cumulatively, so the commit history documents the group’s progress over time. The repository contains only source files such as Python files with the .py or .ipynb extensions and excludes data files, compiled executables, and other non-source materials, together with:
```
<group-repo>/
|-- src # folder containing the source code
|   |-- *.{py/ipynb}
|   |-- requirements.txt # To re-produce the environment
|-- README.md # Instructions on environment setup and code execution
```

This milestone is submitted via Moodle as a group by pasting the public links to the shared code repository and to the milestone report described below. All the submissions above should be in the official language of your program. NO late submission is permitted.

#### Report Requirements (Jupyter Book)
The milestone report is a Jupyter Book maintained in a public repository of its own, separate from the shared code repository, and hosted on that repository’s GitHub Pages. The book grows with the project: this milestone’s report is its first section, and Milestone 2 adds a further section to the same book. The book must present the statistics and analysis of the scraped data, and its figures and tables must be generated during book compilation, not pasted as static screenshots, for quality and interactivity. The report should detail the implementation process, including how the scraping works, the tools and libraries used, for example the arXiv API, OAI-PMH, the Semantic Scholar API, and the requests library, and relevant statistics such as the number of papers scraped successfully, the overall success rate, the average paper size in bytes before and after removing figures, the average number of references per paper, and the average success rate for scraping reference metadata.

The scraper’s performance should also be illustrated through two main points, running time and memory footprint. Running time counts the total time to process one paper, the average time to process each of the required papers, and the total time for entry discovery, while memory footprint counts the maximum RAM used during the scraping, the average RAM consumption, the maximum disk storage required, and the final output’s storage size. Measure both points in an auditable way, for example peak RAM through /usr/bin/time -v or psutil, average RAM through periodic sampling, and disk usage through du. These tools are examples, not requirements. If the system consists of several programs, the runtime is counted as the wall time taken to run the system in an end-to-end way, while the memory footprint is considered as the total memory consumed by the full system. The testbed for the final benchmarking is a Google Colab instance running on CPU-only mode. No upper limit on the running time of the scraper is enforced, while the upper limit on maximum disk usage is given by the Colab instance.

The README.md of the repository stays separate: it provides clear instructions on setting up the necessary environment, such as the Python version and the packages to install through pip or conda, and running the code with specific configurations.

### Grading Criteria
Your grade is determined upon five main criteria as listed below:

Report (Jupyter Book): Does the report illustrate sufficient information as previously mentioned, with figures and tables generated during book compilation?

Source Code: Is the code clean, readable and runnable?

Discovery & Crawling: Are the discovery and download methods used appropriately, with full version coverage of the assigned papers?

Resulted Data: To what extent has the scraper successfully crawled, and how well does the corpus follow the suggested conventions?

Scraper’s Performance: How efficient is the scraper compared to others?