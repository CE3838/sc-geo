# harvest

Jobs that discover and download public sources. Each job must be resumable
(checkpoint progress, skip completed work on restart) and finish within 6
hours. Downloaded PDFs stay out of git.
