#!/usr/bin/env Rscript
# Export the 2D polygons of the ggsegDKT atlas (Desikan-Killiany-Tourville,
# CC0) to JSON, without needing the sf / ggseg packages installed: the atlas
# object stores its geometry as an sf column, which is plain nested lists of
# coordinate matrices underneath.
#
# Usage: export_dkt_polygons.R sysdata.rda out.json
# (sysdata.rda = R/sysdata.rda from github.com/ggseg/ggsegDKT; see makeDoc.txt)

args <- commandArgs(trailingOnly = TRUE)
e <- new.env()
load(args[1], envir = e)
atlas <- get(".dkt", envir = e)
sfd <- atlas$data$sf

rows <- lapply(seq_len(nrow(sfd)), function(i) {
  g <- sfd$geometry[[i]]
  # MULTIPOLYGON -> list of polygons -> list of rings (n x 2 matrices)
  polys <- if (inherits(g, "MULTIPOLYGON")) unclass(g) else list(unclass(g))
  list(
    label = if (is.na(sfd$label[i])) NULL else sfd$label[i],
    view = sfd$view[i],
    polygons = lapply(polys, function(p) lapply(p, function(r) unname(round(r[, 1:2], 3))))
  )
})

json_num <- function(x) format(x, scientific = FALSE, trim = TRUE)
ring_json <- function(r) paste0("[", paste0("[", json_num(r[, 1]), ",", json_num(r[, 2]), "]", collapse = ","), "]")
row_json <- function(x) {
  paste0(
    "{\"label\":", if (is.null(x$label)) "null" else paste0("\"", x$label, "\""),
    ",\"view\":\"", x$view, "\",\"polygons\":[",
    paste(vapply(x$polygons, function(p) paste0("[", paste(vapply(p, ring_json, ""), collapse = ","), "]"), ""), collapse = ","),
    "]}"
  )
}
writeLines(paste0("[", paste(vapply(rows, row_json, ""), collapse = ",\n"), "]"), args[2])
