# This is a collection of mix-in classes for the shell plus their helper functions


import json, logging, re
logger = logging.getLogger(__name__)

from datetime                   import  datetime

from YTCM_api_utils             import  get_video_ids, init_youtube_service, load_api_key

from YTCM_config                import (API_KEY_FILE, CACHING, COMMENTS_FOLDER, COMMENTS_CSV, COMMENTS_GEXF_ON,
                                        COMMENTS_GEXF_OFF, COMMENTS_HTML, COMMENTS_JSON, FILTER_JSON, MAX_RESULTS,
                                        VERSION_DATE)
from YTCM_data_enrichment_utils import  anonymize, deanonymize, detect_languages, sentiment_analysis, review
from YTCM_export_utils          import  convert_json_to_csv, convert_json_to_gephi, convert_json_to_html
from YTCM_filter_utils          import  filter_data, hits
from YTCM_helper_utils          import (check_pending_downloads, clean_dupes, find_duplicate_ids, get_df_comments,
                                        is_youtube_video_id, load_json_file, duplicate_check, validate_data_structure,
                                        save_json_file)
from YTCM_io_utils              import  delete_all_files, load_existing_comments, prepare_output_directory

from YTCM_processing_utils      import  generate_search_list, process_videos

from YTCM_tubeconnect           import  tubeconnect

from YTCM_tubegraph             import (tubegraph, build_interaction_graph, plot_network_graph,
                                        compute_centrality_measures, plot_centrality_results,
                                        channel_video_participation_matrix, plot_channel_clustering_heatmap,
                                        channel_occurrence_stats, plot_top_channels, top_connected_channels,
                                        plot_channel_degree_distribution, build_reply_network, plot_reply_network,
                                        frequent_channel_pairs, plot_channel_pair_network)
from YTCM_tubescope             import (tubescope, plot_comment_likes_distribution, analyze_sentiment_over_time,
                                        plot_sentiment_over_time, group_comments_by_date, plot_comments_over_time,
                                        get_most_liked_comments, calculate_average_sentiment, analyze_replies,
                                        plot_interaction_density_distribution, plot_sentiment_distribution,
                                        plot_participation_timeline, plot_interactions_by_weekday,
                                        plot_views_vs_comments, load_data)
from YTCM_tubetalk              import (tubetalk, plot_language_distribution, plot_language_conflicts,
                                        run_wordcloud, run_topics)


class YTCMCoreCommands:
    def do_info(self, _):
        """
        Show info about the program.
        """

        print("\nYTCM - YouTube Comment Miner")
        print(f"Written by Christoph Hust, current version is from {VERSION_DATE}.")
        print("This is a modular YouTube comments downloader and analyzer, usable for small-to-mid scale research.")
        print("It is designed to be used interactively or in combination with other tools like Gephi or MAXQDA,")
        print("producing fast results with various export formats.\n")
        print("Also incorporated are TubeConnect, a series of tools for network intersection analysis,")
        print("                      TubeGraph, a series of tools for network analysis,")
        print("                      TubeScope, another set of tools for statistical data analysis,")
        print("                  and TubeTalk, a set of tools for linguistic analysis.\n")


    def do_howto(self, _):
        """
        Show information how to use the program.
        """

        print("\nRecommended workflow:")
        print("1. Check the current status of the program by calling 'status'.")
        print("2. If necessary, change primary search terms by calling 'primary' plus parameters.")
        print("3. If necessary, change secondary search terms by calling 'secondary' plus parameters.")
        print("4. If necessary, change excluded terms by calling 'exclude' plus parameters.")
        print("5. If necessary, change search year by calling 'year' plus parameter.")
        print("6. Establish the API setup by calling 'connect'.")
        print("7. Check everything is set up correctly by calling 'status'.")
        print("8. Search for video IDs by calling 'search'.")
        print("9. Download the comments for the video IDs by calling 'download'.")
        print("\nIf the download process is interrupted, you can resume it by")
        print("a. re-starting after the API quota has been reset,")
        print("b. loading the list of un-processed video IDs by calling 'load', and")
        print("c. continuing from step 9.\n")

        print("Recommended analysis workflow:")
        print("1. Review the downloaded comments by calling 'review'.\n")
        print("2. Detect the language of the comments by calling 'language'.\n")
        print("3. Perform sentiment analysis on the comments by calling 'sentiment'.\n")


    def do_status(self, _):
        """
        Show the current status.
        Syntax: status
        """

        c_status = ["off", "on"]
        print(f"API status            : {'ready' if self.youtube else 'not initialized'}")
        print(f"Primary search terms  : {self.primary_terms}")
        print(f"Secondary search terms: {self.secondary_terms}")
        combined = generate_search_list(self.primary_terms, self.secondary_terms)
        print(f"Combined search terms : {combined}")
        print(f"Excluded terms        : {self.excluded_terms}")
        print(f"Search year           : {self.search_year}")
        print(f"Caching               : {c_status[CACHING]}")


    def do_validate(self, arg):
        """
        Validate the JSON file.
        Syntax: validate [silent]
        """

        if arg and arg.strip().lower() == "silent":
            validate_data_structure(COMMENTS_JSON, verbose=False)
        else:
            validate_data_structure(COMMENTS_JSON)


    def do_duplicates(self, arg):
        """
        Check data for duplicate IDs.
        Syntax: duplicates [filename]
        """

        if not arg:
            filename = COMMENTS_JSON
        else:
            filename = arg.strip()

        duplicate_check(filename)


    def do_purgedupes(self, arg):
        """
        Purge duplicate comments and replies.
        Syntax: purgedupes [filename]
        """

        filename = arg.strip() if arg else COMMENTS_JSON

        data = load_json_file(filename)  # dict
        dupes, _occ = find_duplicate_ids(data)  # << use dict-based finder
        report = clean_dupes(data, dupes)  # in-place cleanup
        save_json_file("CLEANED.json", data)
        print(report)


    def do_workflow(self, _):
        """
        Do the predefined workflow: connect, search, download, export.
        Syntax: workflow
        """

        self.do_connect("")

        if not self.youtube:
            print("Error: Connection setup failed, API not initialized.")
            return

        if not self.primary_terms:
            primary = input("Enter primary search terms: ")
            self.do_primary(primary)

            if not self.primary_terms:
                print("Error: No primary search terms.")
                return

        if not self.secondary_terms:
            secondary = input("Enter secondary search terms (optional): ")
            self.do_secondary(secondary)

        if not self.excluded_terms:
            excluded = input("Enter excluded terms (optional): ")
            self.do_exclude(excluded)

        if not self.search_year:
            year = input("Enter search year (YYYY): ")
            self.do_year(year)

            if not self.search_year:
                print("Error: No search year.")
                return

        self.do_search("")

        if not self.video_ids:
            print("\nError: No video IDs found.")
            return

        self.do_download("")
        self.do_export("all")

        print("\nWorkflow completed.")


    def do_reset(self, _):
        """
        Delete all downloaded files. USE WITH CAUTION!
        Syntax: reset
        """

        print("This will delete ALL downloaded files. This cannot be undone.")
        choice = input("Are you sure? Type 'yes' to reset, everything else to cancel: ").strip().lower()

        if choice == "yes":
            delete_all_files()
        else:
            print("Reset cancelled.")


    def do_exit(self, _):
        """
        Quit the program.
        Syntax: exit, quit, q
        """

        print("Goodbye!")
        return True


class YTCMDownloadCommands:
    def do_connect(self, _):
        """
        Get the API key and init the connection to the YouTube databases.
        Syntax: connect
        """

        print("Setting up API key and YouTube access ... ", end="")
        self.api_key = load_api_key(API_KEY_FILE)
        if not self.api_key:
            self.api_key = input("No API key file found on disk. Enter API key manually: ").strip()
            if not self.api_key:
                logger.error("Error: no API key.")
                return

        self.youtube = init_youtube_service(self.api_key)
        if not self.youtube:
            logger.error("Error: unable to initialize a connection to YouTube database.")
            return

        print("done.")
        print("The connection to the YouTube API is now initialized.")


    def do_download(self, arg):
        """
        Load data for current list of video IDs.
        Syntax: download
        """

        if not self.video_ids:
            print("No video ID list in memory. Either do 'search' or 'load' first.")
            return

        if not self.youtube:
            print("API Not initialized. Use 'connect' for API initialization.")
            return

        print(f"Start downloading for {len(self.video_ids)} video IDs.")

        # Prepare folder, load previous comments from file
        prepare_output_directory(COMMENTS_FOLDER)
        all_comments = load_existing_comments(COMMENTS_JSON)

        # Download
        process_videos(self.youtube, self.video_ids, all_comments)

        # Delete processed IDs from file
        remaining_ids = []
        for video_id in self.video_ids:
            if video_id not in all_comments:
                remaining_ids.append(video_id)

        if remaining_ids:
            print(f"{len(remaining_ids)} video IDs could not be downloaded.")
            self.video_ids = remaining_ids
            try:
                with open(self.video_ids_file, "w") as id_file:     # save remaining IDs
                    for video_id in self.video_ids:
                        id_file.write(f"{video_id}\n")
                print(f"List of remaining video IDs in '{self.video_ids_file}' has been updated accordingly.")
            except OSError as e:
                logger.error(f"Error: cannot save remaining video IDs to '{self.video_ids_file}': {e}.")
        else:
            print("All video IDs could be downloaded.")
            self.video_ids = []
            try:
                with open(self.video_ids_file, "w") as _:           # save an empty file
                    pass
            except OSError as e:
                logger.error(f"Error: cannot save an empty list of video IDs to '{self.video_ids_file}': {e}.")


class YTCMEnrichmentCommands:
    def do_review(self, _):
        """
        Do a manual review of the downloaded videos to purge from unwanted content.
        Syntax: review.
        """

        review(COMMENTS_JSON)


    def do_anonymize(self, arg):
        """
        Anonymize the downloaded comments. Running in normal mode will add anonymous ID and channel names to the
        existing data. This can be run iteratively.
        Running in 'purge' mode will create a new file without the original IDs and channel names.
        Syntax: anonymize [purge]
        """

        if not arg:
            anonymize(COMMENTS_JSON)
        else:
            if arg.strip().lower() == "purge":
                anonymize(COMMENTS_JSON, purge=True)
            else:
                print(f"Invalid argument: '{arg}'. Use 'purge' to purge the original IDs and channel names.")


    def do_deanonymize(self, arg):
        """
        Reverses anonymization to prepare a new run.
        Syntax: deanonymize
        """

        deanonymize(COMMENTS_JSON)


    def do_language(self, arg):
        """
        Language detection.
        Syntax: language [rebuild]
        """

        if arg.strip().lower() == "rebuild":
            detect_languages(COMMENTS_JSON, force_rebuild=True)
        else:
            detect_languages(COMMENTS_JSON)


    def do_sentiment(self, arg):
        """
        Sentiment analysis.
        Syntax: sentiment [rebuild]
        """

        if arg.strip().lower() == "rebuild":
            sentiment_analysis(COMMENTS_JSON, force_rebuild=True)
        else:
            sentiment_analysis(COMMENTS_JSON)


class YTCMExportCommands:
    def do_export(self, arg):
        """
        Export the retrieved comments from the file on disk to other formats.
        Syntax: export [format]
        Format: html, gephi, csv, all (default is "all")
        """

        format_choice = arg.strip().lower() if arg else "all"

        if format_choice not in ["html", "gephi", "csv", "all"]:
            print("Invalid export format. Use 'html', 'gephi', 'csv', or 'all'.")
            return

        try:
            with open(COMMENTS_JSON, "r") as f:
                content = f.read().strip()
                if not content:
                    logger.error(f"Error: There are no comments stored in '{COMMENTS_JSON}'.")
                    return
                json.loads(content)  # test JSON integrity to be on the safe side :)

        except FileNotFoundError:
            print(f"The file '{COMMENTS_JSON}' does not exist. Please download comments first.")
            return
        except json.JSONDecodeError as e:
            logger.error(f"Error: JSON structure in '{COMMENTS_JSON}' is corrupted: {e}.")
            return

        if format_choice in ["html", "all"]:
            try:
                print("Exporting as HTML file ... ", end="")
                convert_json_to_html(COMMENTS_JSON, COMMENTS_HTML)
                print(f"done ('{COMMENTS_HTML}').")
            except Exception as e:
                logger.error(f"Error exporting HTML: {e}.")

        if format_choice in ["csv", "all"]:
            try:
                print("Exporting as CSV file ... ", end="")
                convert_json_to_csv(COMMENTS_JSON, COMMENTS_CSV)
                print(f"done ('{COMMENTS_CSV}').")
            except Exception as e:
                logger.error(f"Error exporting CSV: {e}.")

        if format_choice in ["gephi", "all"]:
            try:
                print("Exporting as Gephi network graph ... ", end="")
                convert_json_to_gephi(COMMENTS_JSON, COMMENTS_GEXF_ON, include_replies=True)
                convert_json_to_gephi(COMMENTS_JSON, COMMENTS_GEXF_OFF, include_replies=False)
                print(f"done ('{COMMENTS_GEXF_ON}' and '{COMMENTS_GEXF_OFF}').")
            except Exception as e:
                logger.error(f"Error exporting Gephi network graph: {e}.")


class YTCMFilterCommands:
    def do_filter(self, arg):
        """
        Generate a filtered list of video IDs based on search terms.
        Syntax: filter [--and|--or] term1 term2 ...
        """

        if not arg:
            print("Syntax: filter [--and|--or] term1 term2 ...")
            return

        mode = "and"
        parts = arg.strip().split()

        if parts[0].lower() in ("--and", "--or"):
            mode = parts[0][2:].lower()
            terms = parts[1:]
        else:
            terms = parts

        if not terms:
            print("No search terms provided.")
            return

        if self.filtered_list is None:
            try:
                with open(COMMENTS_JSON, "r", encoding="utf-8") as json_file:
                    unfiltered = json.load(json_file)
            except (IOError, json.JSONDecodeError):
                logger.error("Could not read JSON file.")
                return
        else:
            unfiltered = self.filtered_list

        result = filter_data(unfiltered, terms, mode)

        if not result:
            print("No matches found.")
        else:
            print(f"{len(result)} matching video(s) found.")

        self.filtered_list = result
        self.last_query = terms


    def do_unfilter(self, arg):
        """
        Remove the previously applied filter.
        Syntax: unfilter
        """

        self.filtered_list = None
        self.last_filter = None


    def do_hits(self, arg):
        """
        Show the hits for the last filter.
        Syntax: hits
        """

        if self.filtered_list is None:
            print("No filter applied.")
        elif self.last_query is None:
            print("No search terms stored for snippet highlighting.")
            hits(self.filtered_list, [])
        else:
            hits(self.filtered_list, self.last_query)


    def do_filtersave(self, arg):
        """
        Save the filtered list to a file.
        Syntax: filtersave [filename or default "Filtered.json"]
        """

        if self.filtered_list is None:
            print("No filter applied. Nothing to save.")
            return

        filename = arg.strip() or FILTER_JSON

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(self.filtered_list, f, indent=2, ensure_ascii=False)
            print(f"Filtered data saved to '{filename}'.")
        except IOError as e:
            logging.error(f"Error saving file '{filename}': {e}.")
            print("Could not save file.")


class YTCMSearchCommands:
    def do_primary(self, arg):
        """
        Change the primary search terms.
        Syntax: primary term1 term2 ...
        term1 are separated by spaces or commas; sublists are separated by semicolons.
        "primary" without arguments shows the current primary search terms.
        """

        if not arg:
            print(f"Current primary search terms: {self.primary_terms}.")
            return

        sublists = arg.split(';')
        result = []

        for sublist in sublists:
            if sublist.strip():
                parts = re.split('[, ]+', sublist)
                parts = [part for part in parts if part]
                result.append(parts)

        self.primary_terms = result
        print(f"Primary search terms set to: {self.primary_terms}.")


    def do_secondary(self, arg):
        """
        Change the secondary search terms.
        Syntax: secondary term1 term2 ...
        Terms are separated by spaces or commas.
        "secondary" without arguments shows the current secondary search terms.
        """

        if not arg:
            print(f"Current secondary search terms: {self.secondary_terms}.")
            return

        result = re.split("[, ]+", arg)

        self.secondary_terms = result
        print(f"Secondary search terms set to: {self.secondary_terms}.")


    def do_exclude(self, arg):
        """
        Change the excluded terms.
        Syntax: exclude term1 term2 ...
        Terms are separated by spaces or commas.
        "exclude" without arguments shows the current excluded terms.
        """

        if not arg:
            print(f"Current excluded search terms: {self.excluded_terms}.")
            return

        result = re.split("[, ]+", arg)

        self.excluded_terms = result
        print(f"Excluded search terms set to: {self.excluded_terms}.")


    def do_year(self, arg):
        """
        Change the search year.
        Syntax: year YYYY
        "year" without arguments shows the current search year.
        """

        if not arg:
            print(f"Current search year: {self.search_year}.")
            return

        try:
            year = int(arg.strip())
        except ValueError:
            print("Invalid input. Parameter must be an integer number.")
            return

        current_year = datetime.now().year
        if 2005 <= year <= current_year:
            self.search_year = year
            print(f"Search year set to {self.search_year}.")
        else:
            print(f"Please enter a valid year (range: 2005 until {current_year}).")


    def do_search(self, arg):
        """
        Search for videos and store the resulting IDs in a file.
        Syntax: search [filename]
        """

        if arg:
            self.video_ids_file = arg.strip()

        if not self.primary_terms:
            print("Error: No primary search terms. Use 'primary' to define them.")
            return

        if not self.search_year:
            print("Error: No search year. Use 'year' to set search year.")
            return

        if not self.youtube:
            print("Error: API not initialized. Use 'connect' for API initialization.")
            return

        search_terms = generate_search_list(self.primary_terms, self.secondary_terms)

        print("\nSearching YouTube.com for relevant video IDs ... ", end="")
        self.video_ids = get_video_ids(search_terms, self.youtube, part="snippet",
                                       maxResults=MAX_RESULTS, year=self.search_year,
                                       excluded_terms=self.excluded_terms)
        total_videos = len(self.video_ids)
        print(f"done.\n{total_videos} video IDs found for current search parameters.")

        num = check_pending_downloads(self.video_ids_file)

        if num > 0 and total_videos > 0:
            print(f"There are {num} video IDs pending download in '{self.video_ids_file}'.")
            choice = input(
                "Do you want to add the new files to the IDs on file, or replace the IDs on file (type 'a' or 'r'? ").strip().lower()
            if not choice or choice.startswith("q"):
                print("Aborted.")
                return
            if choice == "r":
                print("Overwriting existing video IDs on file.")
                mode = "w"
            else:
                print("Adding new video IDs to existing ones.")
                mode = "a"
        else:
            mode = "w"

        if total_videos > 0:  # save search results
            try:
                with open(self.video_ids_file, mode) as id_file:
                    for video_id in self.video_ids:
                        id_file.write(f"{video_id}\n")
                print(f"Saved video IDs to '{self.video_ids_file}'.")

                if mode == "a":
                    with open(self.video_ids_file, "r") as f:
                        self.video_ids = [line.strip() for line in f if line.strip()]

            except OSError as e:
                logger.error(f"Error: cannot save video IDs to '{self.video_ids_file}': {e}.")
        else:
            print("No videos found.")


    def do_update(self, arg):
        """
        Update: Reload all video IDs from existing comments file and write them to the download list.
        This will re-download all videos with potentially updated content. Beware of your API quota!
        Syntax: update [filename]
        """

        if arg:
            self.video_ids_file = arg.strip()

        try:
            with open(COMMENTS_JSON, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.error(f"Error: '{COMMENTS_JSON}' not found.")
            return
        except json.JSONDecodeError as e:
            logger.error(f"Error: JSON in '{COMMENTS_JSON}' is invalid: {e}")
            return

        video_ids = list(data.keys())
        total_videos = len(video_ids)

        if total_videos == 0:
            print(f"No video IDs found in '{COMMENTS_JSON}'.")
            return

        num = check_pending_downloads(self.video_ids_file)

        if num > 0:
            print(f"There are {num} video IDs pending download in '{self.video_ids_file}'.")
            choice = input(
                "Do you want to add the updated IDs to the existing list, or replace it? (type 'a' or 'r') ").strip().lower()
            if not choice or choice.startswith("q"):
                print("Aborted.")
                return
            if choice == "r":
                print("Overwriting existing video IDs on file.")
                mode = "w"
            else:
                print("Adding updated video IDs to existing ones.")
                mode = "a"
        else:
            mode = "w"

        try:
            with open(self.video_ids_file, mode) as id_file:
                for video_id in video_ids:
                    id_file.write(f"{video_id}\n")
            print(f"Saved {total_videos} video IDs to '{self.video_ids_file}'.")

            if mode == "a":
                with open(self.video_ids_file, "r") as f:
                    self.video_ids = [line.strip() for line in f if line.strip()]
            else:
                self.video_ids = video_ids

        except OSError as e:
            logger.error(f"Error: cannot save video IDs to '{self.video_ids_file}': {e}.")


    def do_load(self, arg):
        """
        Load video IDs from file to memory.
        Syntax: load [filename]
        """

        filename = arg.strip() if arg else self.video_ids_file

        try:
            with open(filename, "r") as f:
                self.video_ids = [line.strip() for line in f if line.strip()]
            number_of_ids = len(self.video_ids)
            if number_of_ids == 0:
                print(f"There are no video IDs contained in '{filename}'.")
            else:
                print(f"Loaded {number_of_ids} video IDs from '{filename}'.")
        except FileNotFoundError:
            logger.error(f"Error: file '{filename}' does not exist.")
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading video IDs from '{filename}': {e}.")


    def do_addid(self, arg):
        """
        Manually add a video ID to the list of video IDs to be downloaded.
        Syntax: addid [video_id]
        """
        if not arg:
            id = input("Enter video ID: ").strip()
        else:
            id = arg.strip()

        if is_youtube_video_id(id):
            self.video_ids.append(id)
            try:
                with open(self.video_ids_file, "a") as id_file:
                    id_file.write(id + "\n")
                print(f"'{id}' added to download list.")
            except Exception as e:
                logger.error(f"Error adding '{id}' to '{self.video_ids_file}': {e}.")
        else:
            print(f"'{id}' is no valid YouTube video ID.")


class YTCMTubeConnectCommands:
    def do_tubeconnect(self, arg):
        """
        Call TubeConnect for a series of network intersection analyses.
        Syntax: tubeconnect
        """
        tubeconnect()


class YTCMTubeGraphCommands:
    def do_tubegraph(self, arg):
        """
        Call TubeGraph for a series of network analyses on the downloaded comments.
        Syntax: tubegraph [filename]
        """

        if not arg:
            filename = COMMENTS_JSON
        else:
            filename = arg.strip()

        tubegraph(filename)


    def do_interactiongraph(self, arg):
        """
        Show an undirected interaction graph between uploader/commenter/replier.
        Syntax: interactiongraph [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            role_str = input("Include which roles (comma-separated: uploader,commenter,replier)? [all] ").strip()
            roles = tuple([r.strip() for r in role_str.split(",") if r.strip()]) if role_str else ("uploader", "commenter", "replier")
            G = build_interaction_graph(data, roles=roles)

            top_n_in = input("Subgraph of top-N nodes by degree (empty = all)? ").strip()
            top_n = int(top_n_in) if top_n_in else None
            layout = (input("Layout (spring/kamada_kawai/circular/random) [spring]: ") or "spring").strip()

            plot_network_graph(G, top_n=top_n, layout=layout)
        except Exception as e:
            logger.error(f"Error while creating the interaction graph: {e}.")
            print("Error while creating the interaction graph.")


    def do_degreedist(self, arg):
        """
        Show the degree distribution for the undirected interaction graph.
        Syntax: degreedist [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            G = build_interaction_graph(data)
            cap = int(input("Cap bars at which frequency (default 100)? ") or 100)
            bins = int(input("Number of bins (default 30)? ") or 30)
            x_min_in = input("Min degree (optional)? ").strip()
            x_max_in = input("Max degree (optional)? ").strip()
            x_min = int(x_min_in) if x_min_in else None
            x_max = int(x_max_in) if x_max_in else None

            plot_channel_degree_distribution(G, cap_height=cap, bin_count=bins, x_min=x_min, x_max=x_max)

        except Exception as e:
            logger.error(f"Error while creating degree distribution: {e}.")
            print("Error while creating the degree distribution.")


    def do_centralities(self, arg):
        """
        Show the centrality measures for the undirected interaction graph.
        Syntax: centrality [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            G = build_interaction_graph(data)
            centrality_df = compute_centrality_measures(G)
            top = int(input("Top-N for bar chart [10]: ") or 10)
            both_ans = (input("Also show scatter overview (y/n)? [y]: ") or "y").strip().lower()
            both = False if both_ans.startswith("n") else True
            plot_centrality_results(centrality_df, top_n=top, both=both)
        except Exception as e:
            logger.error(f"Error while computing/plotting centrality: {e}.")
            print("Error while computing/plotting centrality.")


    def do_replygraph(self, arg):
        """
        !!! RE-CHECK !!!
        Show a directed reply graph between channels.
        Syntax: replygraph [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            include_self_ans = (input("Include self-replies (y/n)? [n]: ") or "n").strip().lower()
            include_self = True if include_self_ans.startswith("y") else False
            min_weight = int(input("Drop edges with weight below (default 1)? ") or 1)
            G = build_reply_network(data, include_self=include_self, min_weight=min_weight)
            top_n_in = input("Subgraph of top-N nodes by degree (empty = all)? ").strip()
            top_n = int(top_n_in) if top_n_in else None
            plot_reply_network(G, top_n=top_n)
        except Exception as e:
            logger.error(f"Error while creating the reply graph: {e}.")
            print("Error while creating the reply graph.")


    def do_cooccurrence(self, arg):
        """
        Show a channel co-occurrence heatmap/clustermap.
        Syntax: channelheatmap [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            role_str = input("Include which roles (comma-separated: uploader,commenter,replier)? [all] ").strip()
            roles = tuple([r.strip() for r in role_str.split(",") if r.strip()]) if role_str else ("uploader", "commenter", "replier")
            matrix = channel_video_participation_matrix(data, roles=roles, dtype=bool)

            maxch = int(input("Max channels to plot (default 500): ") or 500)
            both_ans = (input("Also show clustermap (y/n)? [y]: ") or "y").strip().lower()
            both = False if both_ans.startswith("n") else True

            plot_channel_clustering_heatmap(matrix, max_channels=maxch, both=both)
        except Exception as e:
            logger.error(f"Error while creating the channel heatmap: {e}.")
            print("Error while creating the channel heatmap.")


    def do_channelstats(self, arg):
        """
        Show occurrence stats per channel.
        Syntax: channelstats [filename]
        """

        filename = arg.strip() if arg.strip() else COMMENTS_JSON
        data = load_data(filename)
        if not data:
            print("No comments to analyze.")
            return

        try:
            df = channel_occurrence_stats(data)
            if df is None or df.empty:
                print("No channel stats could be computed (empty dataset).")
                return

            role_in = (input("Role (uploader/commenter/replier/total) [total]: ") or "total").strip().lower()
            if role_in not in {"uploader", "commenter", "replier", "total"}:
                print("Unknown role, defaulting to 'total'.")
                role_in = "total"

            try:
                top = int((input("Top-N channels [20]: ") or "20").strip())
            except ValueError:
                top = 20
            top = max(1, min(top, len(df)))

            print(f"Using comments file: {filename}")
            print(f"Plotting role: {role_in} | Top-N: {top}")

            plot_top_channels(df, role=role_in, top_n=top)

        except Exception as e:
            logger.error(f"Error while computing/plotting channel stats: {e}.")
            print("Error while computing/plotting channel stats.")

    def do_pairgraph(self, arg):
        """
        Show frequent channel pairs.
        Syntax: pairgraph [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            threshold = int(input("Minimum co-occurrence threshold [3]: ") or 3)
            exclude_ans = (input("Exclude uploader channel from pairs (y/n)? [n]: ") or "n").strip().lower()
            exclude_uploader = True if exclude_ans.startswith("y") else False
            roles_str = input("Restrict roles (comma-separated; uploader,commenter,replier) [all]: ").strip()
            roles = tuple([r.strip() for r in roles_str.split(",") if r.strip()]) if roles_str else ("uploader", "commenter", "replier")
            top_in = input("Only draw top-N pairs (empty = all): ").strip()
            top_n = int(top_in) if top_in else None

            pairs_df = frequent_channel_pairs(data, threshold=threshold, roles=roles, exclude_uploader=exclude_uploader,
                                              top_n=top_n)
            plot_channel_pair_network(pairs_df, top_n=top_n)
        except Exception as e:
            logger.error(f"Error while computing/plotting channel pairs: {e}.")
            print("Error while computing/plotting channel pairs.")


    def do_topdegree(self, arg):
        """
        Show the channels with highest degree in the undirected interaction graph.
        Syntax: topdegree [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            G = build_interaction_graph(data)
            top = int(input("How many top-degree channels to list [10]: ") or 10)
            df = top_connected_channels(G, top_n=top)
            print(df.to_string(index=False))
        except Exception as e:
            logger.error(f"Error while listing top degree channels: {e}.")
            print("Error while listing top degree channels.")


class YTCMTubeScopeCommands:
    def do_tubescope(self, arg):
        """
        Call TubeScope for a series of statistical analyses on the downloaded comments.
        Syntax: tubescope [filename]
        """

        if not arg:
            filename = COMMENTS_JSON
        else:
            filename = arg.strip()

        tubescope(filename)


    def do_likesgraph(self, arg):
        """
        Plot a histogram of likes distribution in the comments.
        Syntax: likesgraph [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        df, _ = get_df_comments(filename)
        if df is None or df.empty:
            print("No comments to analyze.")
            return

        try:
            cap = int(input("Cap bars at which number (default is 100)? ") or 100)
            bins = int(input("Create how many bins (default is 30)? ") or 30)
            x_min = input("Start at which number of likes (optional)? ").strip()
            x_max = input("Stop at which number of likes (optional)? ").strip()
            x_min = int(x_min) if x_min else None
            x_max = int(x_max) if x_max else None
            if x_min and x_max and x_max <= x_min:
                print("Max number must be larger than min number. Ignoring input.")
                x_min, x_max = None, None
        except Exception as e:
            logger.warning(f"Error at data entry: {e}.")
            print("Data validation error.")
            return

        try:
            plot_comment_likes_distribution(df, cap_height=cap, bin_count=bins, x_min=x_min, x_max=x_max)
        except Exception as e:
            logger.error(f"Error while creating likes distribution plot: {e}.")
            print("An error occurred while creating the likes distribution plot.")


    def do_moodline(self, arg):
        """
        Plot a graph of sentiment scores over time.
        Syntax: moodline [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        df, _ = get_df_comments(filename)
        if df is None or df.empty:
            print("No comments to analyze.")
            return

        try:
            sentiment = analyze_sentiment_over_time(df)
            plot_sentiment_over_time(sentiment)
        except Exception as e:
            logger.error("Error while creating sentiment over time plot: {e}.")
            print("Error creating the sentiment over time plot.")


    def do_activityline(self, arg):
        """
        Plot a graph of comment numbers over time.
        Syntax: activityline [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        df, _ = get_df_comments(filename)
        if df is None or df.empty:
            print("No comments to analyze.")
            return

        try:
            timeline = group_comments_by_date(df)
            plot_comments_over_time(timeline)
        except Exception as e:
            logger.error("Error while creating comment number over time plot: {e}.")
            print("Error creating the comment number over time plot.")


    def do_topcomments(self, arg):
        """
        Show a list of the top n most-liked comments.
        Syntax: topcomments [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        df, _ = get_df_comments(filename)
        if df is None or df.empty:
            print("No comments to analyze.")
            return

        try:
            n = int(input("Number of comments to show (default is 5)? ") or 5)
        except:
            n = 5

        if n <= 0:
            print("Top n number must be positive. Setting to default 5.")
            n = 5

        try:
            top_comments = get_most_liked_comments(df, top_n=n)
            print(f"Top {n} most-liked comments:")
            for i, row in top_comments.iterrows():
                text = row["text"][:100] + ("…" if len(row["text"]) > 100 else "")
                print(f"- [{row['likes']} Likes] {text}")
        except Exception as e:
            logger.error(f"Error while creating the top {n} comments list: {e}.")
            print(f"Error while creating the top {n} comments list.")


    def do_sentimentmean(self, arg):
        """
        Show average sentiment over all comments.
        Syntax: sentimentmean [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        df, _ = get_df_comments(filename)
        if df is None or df.empty:
            print("No comments to analyze.")
            return
        try:
            score = calculate_average_sentiment(df)
            print(f"Average VADER sentiment score over all comments: {score:.3f}")
        except Exception as e:
            logger.error(f"Error while calculating the average comments sentiment: {e}.")
            print("Error while creating average comments sentiment.")


    def do_replyquote(self, arg):
        """
        Calculate the quote of comments with replies.
        Syntax: replyquote [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        df, _ = get_df_comments(filename)
        if df is None or df.empty:
            print("No comments to analyze.")
            return

        try:
            ratio = analyze_replies(df)
            print(f"Quote of comments with replies: {ratio:.2f} %")
        except Exception as e:
            logger.error(f"Error while calulating the reply quote: {e}.")
            print(f"Error while calulating the reply quote.")


    def do_interactiondensity(self, arg):
        """
        Calculate an experimental score to measure and plot the interaction density distribution.
        Syntax: interactiondensity [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        _, data = get_df_comments(filename)
        if data is None:
            print("No data available.")
            return

        try:
            bins = int(input("How many bins shall I create (default is 30)? ") or 30)
        except:
            bins = 30

        if bins <= 0:
            print("Number of bins must be positive. Setting to default 30.")
            bins = 30

        try:
            plot_interaction_density_distribution(data, bin_count=bins)
        except Exception as e:
            logger.error(f"Error while creating the interaction density plot: {e}.")
            print("Error while creating the interaction density plot.")


    def do_sentimentdist(self, arg):
        """
        Plot a graph of sentiment distribution in comments data.
        Syntax: do_sentimentdist [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        df, _ = get_df_comments(filename)
        if df is None or df.empty:
            print("No comments to analyze.")
            return

        try:
            plot_sentiment_distribution(df)
        except Exception as e:
            logger.error(f"Error while creating the sentiment distribution graph: {e}.")
            print("Error while creating the sentiment distribution graph.")


    def do_channelline(self, arg):
        """
        Show a timeline of channels participating in the discussion
        Syntax: channelline [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_existing_comments(filename)
        if data is None:
            print("No comments to analyze.")
            return

        plot_participation_timeline(data)


    def do_weekdays(self, arg):
        """
        Show a plot of publication numbers per weekday.
        Syntax: weekdays [filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_existing_comments(filename)
        if data is None:
            print("No comments to analyze.")
            return

        plot_interactions_by_weekday(data)


    def do_viewscorrelation(self, arg):
        """
        Plot how views and comments correlate.
        Syntax: viewscorrelation[filename]
        """

        if arg.strip():
            filename = arg.strip()
        else:
            filename = COMMENTS_JSON

        data = load_existing_comments(filename)
        if data is None:
            print("No comments to analyze.")
            return

        plot_views_vs_comments(data)


class YTCMTubeTalkCommands:
    def do_tubetalk(self, arg):
        """
        Call TubeTalk for a series of NLP-related analyses on the downloaded comments.
        Syntax: tubescope [filename]
        """
        if not arg:
            filename = COMMENTS_JSON
        else:
            filename = arg.strip()

        tubetalk(filename)


    def do_langdist(self, arg):
        """
        Show the language distribution of videos, comments, or replies.
        Syntax: langdist [filename]
        """

        filename = arg.strip() if arg.strip() else COMMENTS_JSON
        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        level = (input("Level (video/comment/reply) [comment]: ") or "comment").strip().lower()
        if level not in ("video", "comment", "reply"):
            print("Invalid level. Use: video, comment, or reply.")
            return

        try:
            top_n = int(input("Top-N [12]: ") or 12)
        except:
            top_n = 12

        norm_ans = (input("Normalize (y/n) [y]: ") or "y").strip().lower()
        normalize = False if norm_ans.startswith("n") else True

        try:
            plot_language_distribution(data=data, level=level, top_n=top_n, normalize=normalize)
        except Exception as e:
            print(f"Error in langdist: {e}")

    def do_langconf(self, arg):
        """
        Show language conflicts (e.g. comment vs. video language).
        Syntax: langconf [filename]
        """

        filename = arg.strip() if arg.strip() else COMMENTS_JSON
        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            top_n = int(input("Top-N [12]: ") or 12)
        except:
            top_n = 12

        norm_ans = (input("Normalize (y/n) [y]: ") or "y").strip().lower()
        normalize = False if norm_ans.startswith("n") else True

        infer_ans = (input("Infer video language if missing? (y/n) [y]: ") or "y").strip().lower()
        infer_video_lang = False if infer_ans.startswith("n") else True

        try:
            min_support = float(input("Min support for inference [0.6]: ") or 0.6)
        except:
            min_support = 0.6

        try:
            majority_threshold = float(input("Majority threshold [0.5]: ") or 0.5)
        except:
            majority_threshold = 0.5

        try:
            plot_language_conflicts(data=data, top_n=top_n, normalize=normalize, infer_video_lang=infer_video_lang,
                                    min_support=min_support, majority_threshold=majority_threshold)
        except Exception as e:
            print(f"Error in langconf: {e}")


    def do_wordcloud(self, arg):
        """
        Show a wordcloud visualization..
        Syntax: wordcloud [filename]
        """

        filename = arg.strip() if arg.strip() else COMMENTS_JSON
        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        start_date = input("Start date (YYYY-MM-DD) [none=beginning]: ").strip() or None
        end_date   = input("End date (YYYY-MM-DD) [none=end]: ").strip() or None

        try:
            n_min = int(input("Min n-gram [1]: ") or 1)
        except:
            n_min = 1
        try:
            n_max = int(input("Max n-gram [1]: ") or 1)
        except:
            n_max = 1

        extra_sw = input("Extra stopwords (comma-separated) [none]: ").strip() or None
        lang_filter = input("Language filter (ISO code) [none]: ").strip() or None

        min_df_raw = input("Min df (abs int or 0..1 float) [2]: ").strip()
        if not min_df_raw:
            min_df = 2
        else:
            try:
                if "." in min_df_raw:
                    min_df = float(min_df_raw)
                else:
                    min_df = int(min_df_raw)
            except:
                min_df = 2

        max_df_raw = input("Max df (0..1 float or int) [0.95]: ").strip()
        if not max_df_raw:
            max_df = 0.95
        else:
            try:
                if "." in max_df_raw:
                    max_df = float(max_df_raw)
                else:
                    max_df = int(max_df_raw)
            except:
                max_df = 0.95

        try:
            max_features = int(input("Max features [5000]: ") or 5000)
        except:
            max_features = 5000

        try:
            run_wordcloud(data=data, start_date=start_date, end_date=end_date, ngram_range=(n_min, n_max),
                          extra_stopwords=[w.strip() for w in extra_sw.split(",")] if extra_sw else None,
                          lang_filter=lang_filter, min_df=min_df, max_df=max_df, max_features=max_features)
        except Exception as e:
            print(f"Error in wordcloud: {e}")


    def do_topics(self, arg):
        """
        Perform a LDA topic modeling analysis.
        Syntax: topics [filename]
        """

        filename = arg.strip() if arg.strip() else COMMENTS_JSON
        data = load_data(filename)
        if data is None:
            print("No comments to analyze.")
            return

        try:
            n_topics = int(input("Number of topics [6]: ") or 6)
        except:
            n_topics = 6
        try:
            n_words = int(input("Top-N words per topic [10]: ") or 10)
        except:
            n_words = 10

        min_df_raw = input("Min df (abs int or 0..1 float) [5]: ").strip()
        if not min_df_raw:
            min_df = 5
        else:
            try:
                min_df = float(min_df_raw) if "." in min_df_raw else int(min_df_raw)
            except:
                min_df = 5

        max_df_raw = input("Max df (0..1 float or int) [0.6]: ").strip()
        if not max_df_raw:
            max_df = 0.6
        else:
            try:
                max_df = float(max_df_raw) if "." in max_df_raw else int(max_df_raw)
            except:
                max_df = 0.6

        try:
            n_min = int(input("Min n-gram [1]: ") or 1)
        except:
            n_min = 1
        try:
            n_max = int(input("Max n-gram [2]: ") or 2)
        except:
            n_max = 2

        try:
            run_topics(data=data, n_topics=n_topics, n_words=n_words, min_df=min_df, max_df=max_df,
                       ngram_range=(n_min, n_max))
        except Exception as e:
            print(f"Error in topics: {e}")
